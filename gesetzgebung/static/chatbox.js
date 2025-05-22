let chatForm, chatInput, chatMessages, urlParams, lawId, hasScrolled;

document.addEventListener('DOMContentLoaded', () => {
    chatForm = document.querySelector(".chat__form");
    chatInput = document.querySelector('.chat__input');
    chatMessages = document.querySelector('.chat__messages');

    // Get law ID from URL
    urlParams = new URLSearchParams(window.location.search);
    lawId = urlParams.get('id');

    chatForm.addEventListener('submit', chatSubmit);

    chatMessages.addEventListener("scroll", () => {
        hasScrolled = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight > 10;
    });
}); 


function createMessage(type, content) {
    const messageDiv = document.createElement('div');
    if (type === 'user') 
        messageDiv.className = "message message__user";
    else 
        messageDiv.className = `message message__assistant message__${type}`;
    messageDiv.innerHTML = marked.parse(content);

    chatMessages.appendChild(messageDiv);
    if (!hasScrolled) chatMessages.scrollTop = chatMessages.scrollHeight;
    return messageDiv;
}

async function chatSubmit(e) {
    e.preventDefault();

    hasScrolled = false;
    
    const message = chatInput.value.trim();
    if (!message) return;

    // Add user message to chat
    createMessage('user', message);
    chatInput.value = '';

    try {
        // Request data from backend
        const response = await fetch('/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
                message: message,
                law_id: lawId
            })
        });
        
        // Check if response is ok
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        // Get a reader from the response body
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let answerText = '';
        let answerDiv = null;
        let buffer = '';
        
        // Process the stream
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            buffer += chunk;
            const lines = buffer.split('\n\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const eventData = JSON.parse(line.substring(6));
                    if (eventData.stage === 'answer' && eventData.chunk) {
                        if (!answerDiv) 
                            answerDiv = createMessage('answer', '');

                        answerText += eventData.chunk;
                        answerDiv.innerHTML = marked.parse(answerText);
                        
                        if (!hasScrolled) 
                            chatMessages.scrollTop = chatMessages.scrollHeight;
                    }
                    else if (eventData.stage === 'status' || eventData.stage === 'error') {
                        createMessage(eventData.stage, eventData.chunk);
                    }
                } catch (error) {
                    const partialData = line.substring(6, 50) + "...";
                    createMessage("error", `Error parsing backend response: ${error}\nParse error at: ${partialData}`);
                }
            }
        }
    } catch (error) {
        createMessage("error", `Error fetching data from the backend: ${error}`);
    }
}