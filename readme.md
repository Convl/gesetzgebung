# Gesetzgebung - A Project for Displaying Information About the Progress of German Laws

## 📌 Project Idea  
The German government provides a portal for tracking the legislative progress of laws at [dip.bundestag.de](https://dip.bundestag.de), but its presentation is not very user-friendly.  

By fetching the government’s data via their API, this project aims to provide:  
- A more user-friendly presentation of legislative progress.  
- Additional features, such as:  
  - Displaying the remaining legislative steps required for a law to take effect.  
  - Integrating news articles / news summaries about a law's progress.  
  - Answering questions about laws via retrieval-augmented generation (RAG).

---

## ⚙️ Main Files & Functions 

### **🔹 `daily_update.py`**  
- Triggered by a cronjob, currently via GitHub Actions. Two core functions: update_laws() and update_news_update_candidates()
- update_laws():
  - Retrieves new/updated laws from the government’s database and transfers them to our own
  - Replaces the dysfunctional page-specific links for documents from the Bundesrat with functioning ones
  - Converts and stores the full text of each Dokument detailing each step in a law's evolution as markdown
  - Adds new laws to the Elasticsearch index. 
  - Marks new steps in a law's evolution for processing in update_news_update_candidates()
- update_news_update_candidates():  
  - Creates a set of search queries for each law
  - Uses those to search for news articles pertaining to a given time period within the law's evolution
  - Creates a summary of the news coverage for that time period if enough articles are found

### **🔹 `routes.py`**  
- Constitutes the backend of the web app. Three core functions: autocomplete(), parse_law() chat()
- autocomplete():
  - Provides a search function for laws using Elasticsearch.
- parse_law():
  - Displays base information about each law, important steps in that law's evolution, news summaries and their sources for that law, and additional steps that still need to happen for the law to take effect, if any.
  - Also accessed from within daily_update (with display=False) to generate some context for the AI to better understand each step in a law's evolution.
- chat():
  - Allows users to ask questions about a law via a chat interface.
  - First evaluates which of the Dokumente pertaining to a law will be relevant for answering the user's question.
  - Then uses the markdown-converted versions of the relevant Dokumente as context for answering the question.

### **🔹 `helpers.py`**  
- Helper functions for parsing laws in `routes.py` and for querying different types of data from LLMs.  

### **🔹 `models.py`**
- Definition of database tables plus some associated functions and objects.

### **🔹 `logger.py`**
- Logger with some customized functionality, currently only really used within daily_update.

### **🔹 `results.html`, `timeline.css`, `autocomplete.css`, `autocomplete.js`, `chatbox.js`, `renderTimelineEvent.js`**
- Basic frontend with mostly vanilla HTML / CSS / JS.
---

## 🔧 Pending Design Improvements 

- Restructure daily_update as a separate module (which it functionally already mostly is).
- Implement propper factory function with more convenient way of setting app-wide config.
- Minor (= re-factoring of get_structured_data_from_ai / get_text_data_from_ai) or major (= integrating agentic framework) rewrite of the AI-associated functionality.
- "Minor" (= re-factoring of the chat route and all HTML/CSS/JS files) or major (= integrating front-end framework) rewrite of the frontend. 
- Ensure thread-safety throughout entire codebase.
- Write more detailed descriptions of how the German legislative process works and what each Vorgangsposition represents to provide better context for generating answers in the chat route.
- Retrieve the true result count for each law from google news and factor that in in the autocomplete route (users more likely to search for laws with lots of press coverage).
- Try vectorizing the markdown-converted Dokumente and only retrieving relevant sections when generating answers in the chat route.
- Try to refine get_news() by first retrieving titles of similar-sounding laws, then making sure the LLM is not erroneously processing news articles pertaining to those laws. 
- Try to come up with intuitive aliases for laws with unintuitive titles, possibly use those in autocomplete route.


## 🚀 Feature Ideas
- Calculate statistics (e.g., average time for a law to move through legislative steps).  
  - Highlight if a law is significantly behind/ahead of schedule. Possibly use web search/AI to suggest reasons why.  
- Visualize success statistics:  
  - What percentage of laws pass, and who proposed them?  
  - Analyze based on governing party, Bundestag/Bundesrat strength at the time.  
- Possibly add a small, horizontal timeline up top that reflects the duration of the legislative steps for the current law, as compared to the average.  
- Maybe create / replace current DIP-abstracts with AI-generated ones.
- Improve overall visual presentation, move more of the associated data-processing into the front-end.  