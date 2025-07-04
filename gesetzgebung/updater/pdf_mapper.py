from typing import Tuple
import pypdfium2.raw as pdfium_c
import pypdfium2
import ctypes
import requests
import re

from gesetzgebung.infrastructure.models import Fundstelle
from gesetzgebung.updater.launch import logger


def map_pdf_without_destinations(fundstelle: Fundstelle, pdf: pypdfium2.PdfDocument) -> int:
    """Maps internal page numbers to external page numbers for a given document.Returns the external page number on which the internal page numbers start. Used for Dokumente from the BR, which do not have destinations set."""

    fundstelle_infos = (
        f"Fundstelle with internal id: {fundstelle.id}, dip id: {fundstelle.dip_id}, url {fundstelle.pdf_url}"
    )

    # Search the upper 15% of each page for any and all numbers and save them in a list of lists
    try:
        num_pages = len(pdf)
        pages = []
        search_area_percent = 0.15

        for page_idx in range(num_pages):
            page = pdf[page_idx]
            page_width, page_height = page.get_size()
            top_search_height = page_height * search_area_percent
            page_text = page.get_textpage()
            top_text = page_text.get_text_bounded(0, page_height - top_search_height, page_width, page_height)
            page_candidates = []
            nums = re.findall(r"\b\d+\b", top_text)
            for num in nums:
                try:
                    n = int(num)
                    page_candidates.append(n)
                except ValueError:
                    continue
            pages.append(page_candidates)

    except Exception as e:
        logger.critical(
            f"Failed to process page {page_idx} of {fundstelle_infos}. Error: {str(e)}",
            subject="Error searching for numbers on top of pdf pages",
        )

    # some setup that accounts for smaller / normal sized documents
    start = None
    offset = None
    done = False
    pages_missing_numbers = 0
    sequences = []
    pages_with_consecutive_numbers_threshold = 10 if len(pages) >= 20 else len(pages) // 2
    verify_last_pages = min(5, len(pages) - pages_with_consecutive_numbers_threshold) if len(pages) > 20 else 0

    # Keep going through the numbers from each page until we find a sequence of 10 (or less, for smaller documents) consecutive numbers. If we do, verify that the sequence holds by also checking the last 5 (or less, for smaller documents) pages.
    for i, page in enumerate(pages):
        if done:
            break

        # empty pages dont have numbers printed on them. This way, they don't break the sequence, but they don't count towards the threshold, either
        if not page:
            pages_missing_numbers += 1
            continue

        continued_sequences = []
        new_sequences = []

        for candidate in page:
            if done:
                break

            continues_sequence = False

            for j, sequence in enumerate(sequences):
                # dont append more than one number to each sequence per page
                if j in continued_sequences:
                    continue

                if candidate == sequence[-1] + 1 + pages_missing_numbers:
                    continues_sequence = True
                    sequence.append(candidate)
                    continued_sequences.append(j)

                    if len(sequence) >= pages_with_consecutive_numbers_threshold:
                        # if our sequence covers the length of the document, we are done
                        if not verify_last_pages or i >= len(pages) - verify_last_pages:
                            done = True
                            start = i - pages_with_consecutive_numbers_threshold + 1
                            offset = candidate - i
                            break
                        else:
                            # check if the sequence still holds for any of the last 5 pages
                            # (technically, just checking the last page should be enough, but this should be a bit more robust)
                            for k in range(len(pages) - 1, len(pages) - 1 - verify_last_pages, -1):
                                if any(final_candidate == candidate + k - i for final_candidate in pages[k]):
                                    done = True
                                    start = i - pages_with_consecutive_numbers_threshold + 1
                                    offset = candidate - i
                                    break

                            if done:
                                break

                            # if it does not, report an error
                            logger.critical(
                                f"Found {pages_with_consecutive_numbers_threshold} consecutive numbers on pages {i - pages_with_consecutive_numbers_threshold} to {i}.\n"
                                f"However, none of the last {verify_last_pages} pages have the expected internal page number {candidate + len(pages) - i}.\n"
                                f"Error occurred on {fundstelle_infos}.",
                                subject="Failed to verify page number sequence against final pages",
                            )

            # if the candidate did not continue any sequences, it may be the start of a new sequence
            if not continues_sequence:
                new_sequences.append([candidate])

        pages_missing_numbers = 0

        # remove sequences that were not continued on the current page
        for j in range(len(sequences) - 1, -1, -1):
            if j not in continued_sequences:
                sequences.pop(j)

        sequences += new_sequences

    # return result or throw error. We need to return offset - 1, because our list was 0-indexed, but to the reader, pdf pages are 1-indexed (likewise, start would have to be +1, if it was going to be returned at all)
    if start and offset is not None:
        logger.info(
            f"Finished mapping internal page numbers for {fundstelle_infos}.\n"
            f"Internal page numbers start on internal page {start + 1} (1-indexed), which has external page number {start + offset}, making the offset {offset - 1}."
        )
        return offset - 1
    else:
        logger.critical(
            f"Could not find a sequence of {pages_with_consecutive_numbers_threshold} consecutive numbers on the first {len(pages)} pages.\n"
            f"Error occurred on {fundstelle_infos}.",
            subject="Could not find a sequence of page numbers",
        )


def map_pdf_with_destinations(fundstelle: Fundstelle, pdf: pypdfium2.PdfDocument) -> dict:
    """
    Get all named destinations from a PDF file. Used for pdf files from the Bundestag, where internal page numbers are layed out as named destinations.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        A dictionary mapping destination names to page numbers
    """

    fundstelle_infos = (
        f"Fundstelle with internal id: {fundstelle.id}, dip id: {fundstelle.dip_id}, url: {fundstelle.pdf_url}"
    )
    if fundstelle.anfangsseite is None or fundstelle.endseite is None:
        logger.critical(
            f"Error occurd on {fundstelle_infos}",
            subject="Missing anfangsseite or endseite",
        )
        return {}

    anfangsseite = fundstelle.anfangsseite
    endseite = fundstelle.endseite
    offset = endseite - anfangsseite
    if offset < 0:
        logger.critical(
            f"Error occurd on {fundstelle_infos}",
            subject="Anfangsseite is greater than endseite",
        )
        return {}

    doc_handle = pdf.raw

    # get the count of named destinations
    count = pdfium_c.FPDF_CountNamedDests(doc_handle)

    destinations = {}

    # For each destination
    for i in range(count):

        # First, get the required buffer size
        buflen = ctypes.c_long(0)
        dest_handle = pdfium_c.FPDF_GetNamedDest(doc_handle, i, None, ctypes.byref(buflen))

        if not dest_handle:
            logger.debug(f"No destination found for index {i}")
            continue

        # If buffer length is returned as <= 0, something went wrong
        if buflen.value <= 0:
            logger.warning(f"Error getting buffer size for destination {i}")
            continue

        # Allocate buffer for the destination name
        buffer = ctypes.create_string_buffer(buflen.value)

        # Second call to get the actual name
        pdfium_c.FPDF_GetNamedDest(doc_handle, i, buffer, ctypes.byref(buflen))

        # Skip the last 2 bytes which are null terminators
        name_bytes = buffer.raw[: buflen.value - 2]

        # Convert from UTF-16LE to Python string
        try:
            dest_name = name_bytes.decode("utf-16le")
            # Get the page index from the destination handle
            page_index = pdfium_c.FPDFDest_GetDestPageIndex(doc_handle, dest_handle)

            # Page indices are 0-based in PDFium, convert to 1-based for user-friendly display
            page_number = page_index + 1 if page_index >= 0 else None

            destinations[dest_name] = page_number
        except UnicodeDecodeError:
            logger.warning(
                f"Error decoding destination name or page number at index {i} / {count} for {fundstelle_infos}"
            )

    logger.info(f"found {len(destinations.keys())} named destinations")

    mapped_anfangsseite, mapped_endseite = None, None

    # The function should return at this point if the DIP values for anfangsseite and endseite are in the destinations dictionary
    if (mapped_anfangsseite := destinations.get(f"P.{anfangsseite}", None)) and (
        mapped_endseite := destinations.get(f"P.{endseite}", None)
    ):
        logger.info(
            f"Successfully mapped anfangsseite {anfangsseite} to external anfangsseite: {mapped_anfangsseite} and endseite {endseite} to external endseite {mapped_endseite} for {fundstelle_infos}"
        )
        return destinations

    # if we get here, the DIP values for anfangsseite and endseite are not in the destinations dictionary, so we need to approximate them
    lowest_destination = min(
        int(k.split(".")[1]) for k in destinations.keys() if k.startswith("P.") and k.split(".")[1].isdigit()
    )
    highest_destination = max(
        int(k.split(".")[1]) for k in destinations.keys() if k.startswith("P.") and k.split(".")[1].isdigit()
    )

    def approximate_destination(seite):
        i = 1
        mapped_seite = None
        while not (mapped_seite := destinations.get(f"P.{seite - i}", None)) and seite - i >= lowest_destination:
            i += 1
        if mapped_seite:
            return mapped_seite + i

        i = 1
        while not (mapped_seite := destinations.get(f"P.{seite + i}", None)) and seite + i <= highest_destination:
            i += 1
        if mapped_seite:
            return mapped_seite - i

        logger.warning(
            f"Failed to approximate destination for {fundstelle_infos}, page: {seite}, destinations: {destinations}",
        )
        return None

    mapped_anfangsseite = mapped_anfangsseite or approximate_destination(anfangsseite)
    mapped_endseite = mapped_endseite or approximate_destination(endseite)

    # if the approximation failed for either anfangsseite or endseite, we try to approximate it based on the other one and the offset
    mapped_anfangsseite = mapped_anfangsseite or (mapped_endseite - offset if mapped_endseite else None)
    mapped_endseite = mapped_endseite or (mapped_anfangsseite + offset if mapped_anfangsseite else None)

    if mapped_anfangsseite and mapped_endseite:
        if mapped_anfangsseite > mapped_endseite:
            logger.critical(
                f"Invalid destination mapping - anfangsseite is greater than endseite. This happened on {fundstelle_infos}, anfangsseite: {anfangsseite}, endseite: {endseite}, mapped_anfangsseite: {mapped_anfangsseite}, mapped_endseite: {mapped_endseite}, destinations: {destinations}",
                subject="Failed to map destinations, anfangsseite is greater than endseite",
            )
            return {}
        else:
            destinations[f"P.{anfangsseite}"] = mapped_anfangsseite
            destinations[f"P.{endseite}"] = mapped_endseite
            logger.info(
                f"Successfully mapped anfangsseite {anfangsseite} to external anfangsseite: {mapped_anfangsseite} and endseite {endseite} to external endseite {mapped_endseite} for {fundstelle_infos}"
            )
            return destinations
    else:
        logger.critical(
            f"Failed to map destinations for {fundstelle_infos}, destinations: {destinations}",
            subject="Failed to map destinations",
        )
        return {}


def get_pdf(fundstelle: Fundstelle) -> Tuple[pypdfium2.PdfDocument, bytes]:
    """Helper function to download a pdf (used for mapping pages / converting to markdown). Returns a tuple of the pypdfium2 PdfDocument, and the raw response content"""
    try:
        with requests.get(fundstelle.pdf_url) as response:
            response.raise_for_status()
            pdf_content = response.content
            pdf = pypdfium2.PdfDocument(pdf_content)
            return pdf, pdf_content

    except Exception as e:
        logger.error(
            f"Could not download pdf. Error occurred on Fundstelle {fundstelle.id} with url {fundstelle.pdf_url}.\n Error: {e}",
            subject="Error downloading pdf document from Fundstelle",
        )
        return None, None
