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
    document.getElementById('autocomplete').value = suggestion.titel;
    document.getElementById('id').value = suggestion.id;
    document.getElementById('suggestions').innerHTML = ''; // Hide suggestions after selection
    document.getElementById('suggestions').classList.remove('active');  // Hide suggestions after selection
    document.querySelector('form').submit(); 
}