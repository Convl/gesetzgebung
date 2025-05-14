function fetchSuggestions() {
    const query = document.getElementById('autocomplete').value;
    
    if (query.length > 0) {
        fetch(`/autocomplete?q=${encodeURIComponent(query)}`)
            .then(response => response.json())
            .then(data => {
                showSuggestions(data);
            })
            .catch(error => console.error('Error fetching suggestions:', error));
    } else {
        document.getElementById('suggestions').innerHTML = '';
        document.getElementById('suggestions').classList.remove('active');  // Hide suggestions if no input
    }
}

function showSuggestions(suggestions) {
    const suggestionsContainer = document.getElementById('suggestions');
    suggestionsContainer.innerHTML = ''; // Clear previous suggestions

    if (suggestions.length > 0) {
        suggestionsContainer.classList.add('active'); // Show suggestions dropdown

        suggestions.forEach(item => {
            const div = document.createElement('div');
            div.classList.add('suggestion-item');
            div.textContent = item.titel;
            div.onclick = () => selectSuggestion(item);
            suggestionsContainer.appendChild(div);
        });
    } else {
        suggestionsContainer.classList.remove('active'); // Hide suggestions if no data
    }
}

function selectSuggestion(suggestion) {
    document.getElementById('suggestions').innerHTML = ''; // Hide suggestions after selection
    document.getElementById('suggestions').classList.remove('active'); 
    handleSubmit(suggestion.titel, suggestion.id);
}

function handleFormSubmit(event) {
    event.preventDefault();

    const titel = document.getElementById('autocomplete').value;
    let id = document.getElementById('id').value;

    if (!id) {
        fetch(`/autocomplete?q=${encodeURIComponent(titel)}`)
            .then(response => response.json())
            .then(suggestions => {
                const match = suggestions.find(item => item.titel.toLowerCase() === titel.toLowerCase());
                id = match ? match.id : NaN;
                handleSubmit(titel, id); // Call handleSubmit only after resolving the ID
            })
            .catch(error => {
                console.error('Error fetching suggestions:', error);
                handleSubmit(titel, NaN); 
            });
    } else {
        handleSubmit(titel, id);
    }
}


function handleSubmit(titel, id) {
    const titelSlug = encodeURIComponent(titel.replace(/\s+/g, '-').toLowerCase());
    const idSlug = id ? encodeURIComponent(id.replace(/\s+/g, '-').toLowerCase()) : "";

    window.location.href = `/submit/${titelSlug}?id=${idSlug}`;
}

function handleKeydown(event) {
    if (event.key === 'Escape') {
        document.getElementById('suggestions').classList.remove('active');
    }
}