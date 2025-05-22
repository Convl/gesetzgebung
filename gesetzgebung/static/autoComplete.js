"use strict";

const searchField = document.querySelector("#law_search_term");
const autoCompleteSuggestions = document.querySelector(".autocomplete-suggestions");

const FETCH_DELAY = 300;
let lastFetchTime = 0;
let currentItem = null;

searchField.addEventListener("keydown", e => handleKeyNavigation(e));
searchField.addEventListener("input", () => {
    const now = Date.now();
    if(now - lastFetchTime > FETCH_DELAY) {
        lastFetchTime = now;
        fetchSuggestions();
    }
});

document.addEventListener("click", (e) => {
    if(!autoCompleteSuggestions.contains(e.target) && e.target != searchField) {
        cleanUp();
    }
});


function handleKeyNavigation (e) {
    let suggestions = autoCompleteSuggestions.children;
    let highlightSuggestion = (i) => {
        for(let i = 0; i < suggestions.length; i++) {
            if(i === currentItem) {
                suggestions[i].classList.add("focussed");
                suggestions[i].scrollIntoView({ block: 'nearest' });
            }
            else {
                suggestions[i].classList.remove("focussed");
            }
        }
    }

    switch(e.key) {
        case 'Escape':
            cleanUp();
            break;

        case 'ArrowDown':
            currentItem === null ? currentItem = 0 : currentItem = Math.min(currentItem + 1, suggestions.length - 1);
            highlightSuggestion(currentItem);
            break;
                
        case 'ArrowUp':
            if(currentItem !== null && currentItem !== 0) {
                currentItem--;
                highlightSuggestion(currentItem)
            }
            break;

        case 'Enter':
            e.preventDefault();
            if(currentItem !== null && currentItem < suggestions.length) {
                suggestions[currentItem].dispatchEvent(new Event("click"));
            }
    }
}

async function fetchSuggestions() {
    currentItem = null;

    if(!searchField.value) {
        autoCompleteSuggestions.style.display = "none";
        return;
    }

    let searchResults;
    try {
        const response = await fetch(`/autocomplete?q=${encodeURIComponent(searchField.value)}`);
        if(!response.ok) {
            throw new Error(`Http Error: ${response.status}`);
        }
        searchResults = await response.json();
    }
    catch(error) {
        console.error('Error fetching suggestions:', error);
        autoCompleteSuggestions.innerHTML='';
        const showError = document.createElement("div");
        showError.classList.add("suggestion-item");
        showError.textContent = "Error retrieving laws from the database";
        autoCompleteSuggestions.appendChild(showError);
        return;
    }
    
    autoCompleteSuggestions.innerHTML = '';
    autoCompleteSuggestions.style.display = "block";
    for(let searchResult of searchResults) {
        const suggestion = document.createElement("div");
        suggestion.classList.add("suggestion-item");
        suggestion.setAttribute("tabindex", "0");
        suggestion.textContent = searchResult["titel"];
        suggestion.addEventListener("click", () => handleSubmit(searchResult));
        autoCompleteSuggestions.appendChild(suggestion);
    }
}

function handleSubmit(item) {
    cleanUp();
    const titelSlug = encodeURIComponent(item["titel"].replace(/\s+/g, '-').toLowerCase());
    const idSlug = encodeURIComponent(item["id"].replace(/\s+/g, '-').toLowerCase());
    window.location.href = `/submit/${titelSlug}?law_id=${idSlug}`;
}

function cleanUp() {
    autoCompleteSuggestions.innerHTML = '';
    autoCompleteSuggestions.style.display = "none";
    currentItem = null;
}