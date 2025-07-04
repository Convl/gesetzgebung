# this module is a complete mess and probably most in need of a re-write / replacement

import datetime
import json
import re
import time

from openai import OpenAI

from gesetzgebung.logic.backoff import ExpBackoffException, exp_backoff
from gesetzgebung.logic.webapp_logger import webapp_logger


def get_structured_data_from_ai(
    client: OpenAI,
    messages: list[dict],
    schema: dict = None,
    subfield: str = None,
    models: list[str] = ["deepseek/deepseek-r1"],
    temperature: float = 0.3,
    attempts: int = 1,
    delay: int = 1,
) -> list[dict]:
    """Requests and extracts structured (json) data from an ai with optional exponential backoff.

    Args:
    client: OpenAI client instance
    messages: List of message dictionaries for the conversation
    schema: JSON schema for structured response validation
    subfield: Extract specific field from response instead of full object
    models: List of model names to try in order of preference
    temperature: Sampling temperature for response generation
    attempts: Maximum number of attempts per model on failure
    delay: Base delay in seconds for exponential backoff

    Returns:
        Parsed JSON response from the AI model
    """

    def _get_structured_data_from_ai():
        """ "Implementation function that gets decorated with exponential backoff."""
        ai_response, message, content = None, None, None
        # Openrouter models parameter is supposed to pass the query on to the next model if the first one fails, but currently only works for some types of errors, so we manually iterate instead
        for i, model in enumerate(models):
            try:
                response = client.chat.completions.create(
                    model=model,
                    extra_body={
                        "models": models[i + 1 :],
                        "provider": {
                            "require_parameters": True,
                            "sort": "throughput",
                        },
                        "temperature": temperature,
                    },
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": schema,
                    },
                )
                if (
                    isinstance(response.choices, list)
                    and len(response.choices) > 0
                    and (message := getattr(response.choices[0], "message"))
                    and (content := getattr(message, "content"))
                ):
                    break
                else:
                    webapp_logger.warning(f"Error with model {model}: Invalid response {response}")
            except Exception as e:
                webapp_logger.warning(f"Error with model {model}: {e}")

        if content is None:
            raise ExpBackoffException(
                f"Could not get a valid response from any model out of {models} with messages: {messages}."
            )

        try:
            ai_response = content
            # next two lines should not be necessary any more, included just to be on the safe side
            ai_response = re.sub(r"<think>.*?</think>", "", ai_response, flags=re.DOTALL)
            ai_response = re.sub(r"```json\n(.*?)\n```", r"\1", ai_response, flags=re.DOTALL)
            ai_response = json.loads(ai_response).get(subfield, None) if subfield else json.loads(ai_response)
            return ai_response

        except Exception as e:
            raise ExpBackoffException(f"Could not parse AI response: {ai_response}\nFrom: {content}\n\n Error: {e}.")

    decorated = exp_backoff(attempts=attempts, base_delay=delay, terminate_on_final_failure=False)(
        _get_structured_data_from_ai
    )
    return decorated()


def get_text_data_from_ai(client, messages, models=None, stream=False, temperature=0.5):
    # models = ['deepseek/deepseek-r1', 'deepseek/deepseek-chat', 'openai/gpt-4o-2024-11-20']
    models = models or ["deepseek/deepseek-r1"]
    if not stream:
        delay = 1
        for retry in range(13):
            # Openrouter models parameter is supposed to pass the query on to the next model if the first one fails, but currently only works for some types of errors, so we manually iterate
            for i, model in enumerate(models):
                response = client.chat.completions.create(
                    model=model,
                    extra_body={
                        "models": models[i + 1 :],
                        "provider": {"sort": "throughput"},
                        "temperature": temperature,
                    },
                    messages=messages,
                )
                if response.choices:
                    break

            try:
                ai_response = response.choices[0].message.content
                # this shouldn't be necessary, but just in case
                ai_response = re.sub(r"<think>.*?</think>", "", ai_response, flags=re.DOTALL)
                ai_response = re.sub(r"```json\n(.*?)\n```", r"\1", ai_response, flags=re.DOTALL)
                return ai_response

            except Exception as e:
                print(
                    f"Could not parse AI response {ai_response}\nFrom: {response.choices[0].message.content}\n\n Error: {e}. Retrying in {delay} seconds."
                )
                time.sleep(delay)
                delay *= 2

        webapp_logger.critical(
            "Error getting structured data from AI",
            f"Could not get text data from AI. Time: {datetime.datetime.now()}, Messages: {messages}.",
        )
    else:
        for i, model in enumerate(models):
            try:
                stream_response = client.chat.completions.create(
                    model=model,
                    extra_body={
                        "models": models[i + 1 :],
                        "provider": {"sort": "throughput"},
                        "temperature": 0.5,
                    },
                    messages=messages,
                    stream=True,  # Enable streaming
                )

                # Return a generator that yields each chunk
                def generate():
                    full_text = ""
                    last_activity = time.time()
                    idle_timeout = 20

                    try:
                        for chunk in stream_response:
                            if hasattr(chunk, "error") or (hasattr(chunk, "object") and chunk.object == "error"):
                                error_details = getattr(chunk, "error", {})
                                error_message = getattr(error_details, "message", "Unknown provider error")
                                error_code = getattr(error_details, "code", "unknown")

                                formatted_error = f"Error: {error_message}"
                                if error_code != "unknown":
                                    formatted_error += f" (code: {error_code})"

                                print(f"Received error event in stream: {formatted_error}")
                                yield {
                                    "chunk": formatted_error,
                                    "error": "provider_error",
                                }

                            last_activity = time.time()

                            if hasattr(chunk.choices[0], "delta") and hasattr(chunk.choices[0].delta, "content"):
                                content = chunk.choices[0].delta.content
                                if content is not None:
                                    full_text += content
                                    yield {"chunk": content, "full_text": full_text}

                            # Check for finish reason if available
                            if hasattr(chunk.choices[0], "finish_reason") and chunk.choices[0].finish_reason:
                                print(f"Stream finished with reason: {chunk.choices[0].finish_reason}")
                                break
                            current_time = time.time()
                            if current_time - last_activity > idle_timeout:
                                print(f"Stream idle for {idle_timeout} seconds, terminating")
                                if full_text:
                                    yield {
                                        "chunk": "\n\n[Response timed out]",
                                        "full_text": full_text + "\n\n[Response timed out]",
                                        "error": "stream_timeout",
                                    }
                                break

                    except Exception as e:
                        print(f"Exception in chunk processing: {e}")
                        print(f"Exception type: {type(e)}")
                        print(f"Exception dir: {dir(e)}")

                        yield {"chunk": f"Error: {str(e)}", "error": True}

                return generate()

            except Exception as e:
                print(f"Error with model {model}: {e}")
                print(f"Exception type: {type(e)}")
                print(f"Exception dir: {dir(e)}")

                def error_generator(e):
                    yield {"chunk": f"Error: {str(e)}", "error": True}

                return error_generator(e)

    webapp_logger.critical(
        "Error getting streaming data from AI",
        f"All models failed for streaming request. Time: {datetime.datetime.now()}, Messages: {messages}.",
    )

    # Return an empty generator
    def empty_generator():
        yield {
            "chunk": "Error: All models failed",
            "full_text": "Error: All models failed",
        }

    return empty_generator()


# TODO: Test and implement throughout codebase, or move to agentic framework altogether
def query_ai(
    client: OpenAI,
    messages: list[dict],
    schema: dict = None,
    subfield: str = None,
    models: list[str] = ["deepseek/deepseek-r1"],
    structured: bool = False,
    stream: bool = False,
    temperature: float = 0.3,
    attempts: int = 1,
    delay: int = 1,
) -> list[dict]:
    """Requests and extracts (structured) data from an ai with optional exponential backoff.

    Args:
    client: OpenAI client instance
    messages: List of message dictionaries for the conversation
    schema: JSON schema for structured response validation
    subfield: Extract specific field from response instead of full object
    models: List of model names to try in order of preference
    structured: Indicator whether or not to return structured data
    stream: Indicator whether or not to stream response
    temperature: Sampling temperature for response generation
    attempts: Maximum number of attempts per model on failure
    delay: Base delay in seconds for exponential backoff

    Returns:
        Response from the AI model, as either plain text or parsed JSON
    """

    def _query_ai_non_streaming(attempt=1):
        """ "Implementation function for returning text or structured data without streaming. Gets decorated with exponential backoff."""
        ai_response, message, content = None, None, None
        params = {
            "extra_body": {
                "provider": {
                    "sort": "throughput",
                },
                "temperature": temperature,
            },
            "messages": messages,
            "stream": stream,
        }
        if structured:
            params["extra_body"]["provider"]["require_parameters"] = True
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": schema,
            }
        # Openrouter models parameter is supposed to pass the query on to the next model if the first one fails, but currently only works for some types of errors, so we manually iterate instead
        for i, model in enumerate(models):
            params["model"] = model
            params["extra_body"]["models"] = models[i + 1 :]
            try:
                response = client.chat.completions.create(**params)
                if (
                    isinstance(response.choices, list)
                    and len(response.choices) > 0
                    and (message := getattr(response.choices[0], "message"))
                    and (content := getattr(message, "content"))
                ):
                    break
                else:
                    webapp_logger.warning(f"Error with model {model}: Invalid response {response}")
                    continue
            except Exception as e:
                webapp_logger.warning(f"Error with model {model}: {e}")

        if content is None:
            raise ExpBackoffException(
                f"Could not get a valid response from any model out of {models} with messages: {messages}."
            )

        try:
            ai_response = content
            # next two lines should not be necessary any more, included just to be on the safe side
            ai_response = re.sub(r"<think>.*?</think>", "", ai_response, flags=re.DOTALL)
            ai_response = re.sub(r"```json\n(.*?)\n```", r"\1", ai_response, flags=re.DOTALL)
            if structured:
                ai_response = json.loads(ai_response).get(subfield, None) if subfield else json.loads(ai_response)
            return ai_response

        except Exception as e:
            raise ExpBackoffException(f"Could not parse AI response: {ai_response}\nFrom: {content}\n\n Error: {e}.")

    def _query_ai_streaming(attempt=1):
        """ "Implementation function for streaming text responses. Gets decorated with exponential backoff."""
        params = {
            "extra_body": {
                "provider": {
                    "sort": "throughput",
                },
                "temperature": temperature,
            },
            "messages": messages,
            "stream": stream,
        }
        # Openrouter models parameter is supposed to pass the query on to the next model if the first one fails, but currently only works for some types of errors, so we manually iterate instead
        for i, model in enumerate(models):
            params["model"] = model
            params["extra_body"]["models"] = models[i + 1 :]
            try:
                response = client.chat.completions.create(**params)
                for chunk in generate_chunks(response):
                    yield chunk
                    if attempt == 1:
                        raise ExpBackoffException("blub")
                return
            except Exception as e:
                webapp_logger.warning(f"Error with model {model}: {e}")

        # yield {"chunk": f"All models have failed", "error": True}
        raise ExpBackoffException(
            f"Could not get a valid response from any model out of {models} with messages: {messages}."
        )

    decorated = exp_backoff(
        attempts=attempts, base_delay=delay, terminate_on_final_failure=False, pass_attempt_count=True
    )(_query_ai_streaming if stream else _query_ai_non_streaming)
    return decorated()


def generate_chunks(response):
    full_text = ""
    last_activity = time.time()
    idle_timeout = 20

    try:
        for chunk in response:
            if hasattr(chunk, "error") or (hasattr(chunk, "object") and chunk.object == "error"):
                error_details = getattr(chunk, "error", {})
                error_message = getattr(error_details, "message", "Unknown provider error")
                error_code = getattr(error_details, "code", "unknown")
                formatted_error = f"Received error event in stream: Error: {error_message}, code: {error_code}"

                webapp_logger.warning(formatted_error)
                yield {
                    "chunk": formatted_error,
                    "error": "provider_error",
                }

            last_activity = time.time()

            if hasattr(chunk, "choices") and isinstance(chunk.choices, list) and len(chunk.choices) > 0:
                # append content, if available
                if hasattr(chunk.choices[0], "delta") and hasattr(chunk.choices[0].delta, "content"):
                    content = chunk.choices[0].delta.content
                    if content is not None:
                        full_text += content
                        yield {"chunk": content, "full_text": full_text}

                # Check for finish reason if available
                if hasattr(chunk.choices[0], "finish_reason") and chunk.choices[0].finish_reason:
                    webapp_logger.info(f"Stream finished with reason: {chunk.choices[0].finish_reason}")
                    break

                current_time = time.time()
                if current_time - last_activity > idle_timeout:
                    webapp_logger.error(
                        f"Stream idle for {idle_timeout} seconds, terminating", subject="Stream timed out"
                    )
                    if full_text:
                        yield {
                            "chunk": "\n\n[Response timed out]",
                            "full_text": full_text + "\n\n[Response timed out]",
                            "error": "stream_timeout",
                        }
                    break

    except Exception:
        raise
