
document.addEventListener('DOMContentLoaded', function() {
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');

    // Get law ID from URL
    const urlParams = new URLSearchParams(window.location.search);
    const lawId = urlParams.get('id');

    chatForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const message = chatInput.value.trim();
        if (!message) return;

        // Add user message to chat
        appendMessage('user', message);
        chatInput.value = '';

        try {
            // Make the fetch request
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
            
            // Process the stream
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                
                const chunk = decoder.decode(value, { stream: true });
                
                // Process each line (event) in the chunk
                const lines = chunk.split('\n\n');
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const eventData = JSON.parse(line.substring(6));
                            
                            // Handle different message stages
                            if (eventData.stage === 'status' || eventData.stage === 'documents') {
                                const messageDiv = document.createElement('div');
                                messageDiv.className = 'message assistant-message';
                                messageDiv.innerHTML = marked.parse(eventData.chunk);
                                chatMessages.appendChild(messageDiv);
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                            }
                            else if (eventData.stage === 'error') {
                                const errorDiv = document.createElement('div');
                                errorDiv.className = 'message assistant-message error-message';
                                errorDiv.innerHTML = marked.parse(eventData.chunk);
                                chatMessages.appendChild(errorDiv);
                                chatMessages.scrollTop = chatMessages.scrollHeight;
                                break;
                            }
                            else if (eventData.stage === 'answer') {
                                // For answer chunks, update a single message
                                if (!answerDiv) {
                                    answerDiv = document.createElement('div');
                                    answerDiv.className = 'message assistant-message answer-message';
                                    chatMessages.appendChild(answerDiv);
                                }
                                
                                if (eventData.chunk) {
                                    answerText += eventData.chunk;
                                    answerDiv.innerHTML = marked.parse(answerText);
                                    chatMessages.scrollTop = chatMessages.scrollHeight;
                                }
                            }
                        } catch (e) {
                            console.error('Error parsing event data:', e, line);
                        }
                    }
                }
            }
        } catch (error) {
            console.error('Fetch error:', error);
            const errorDiv = document.createElement('div');
            errorDiv.className = 'message assistant-message error-message';
            errorDiv.textContent = 'Fehler bei der Verarbeitung der Anfrage.';
            chatMessages.appendChild(errorDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    });

    function appendMessage(sender, text) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}-message`;
        
        if (sender === 'assistant') {
            messageDiv.innerHTML = marked.parse(text);
        } else {
            messageDiv.textContent = text;
        }
        
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
}); 