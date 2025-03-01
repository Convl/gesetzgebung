# Gesetzgebung - A Project for Displaying Information About the Progress of German Laws

## 📌 Project Idea  
The German government provides a portal for tracking the legislative progress of laws at [dip.bundestag.de](https://dip.bundestag.de), but its presentation is not very user-friendly.  

By fetching the government’s data via their API, this project aims to provide:  
- A more user-friendly presentation of legislative progress.  
- Additional features, such as:  
  - Displaying the remaining legislative steps required for a law to take effect.  
  - Integrating news articles about a law's progress.  

---

## ⚙️ Main Files & Functions 

### **🔹 `daily_update.py`**  
- Retrieves new/updated laws from the government’s database and transfers them to our own.  
- Adds new laws to the Elasticsearch index.  
- At certain intervals:  
  - Searches for news articles about recent legislative events.  
  - Stores up to 5 articles + a summary in the database.  

### **🔹 `routes.py`**  
- Parses laws from the database for display on the website.  
- All HTML formatting is currently done via string manipulation (may move this to the frontend in the future).  
- Provides a search function for laws using Elasticsearch.  

### **🔹 `helpers.py`**  
- Helper functions for parsing laws in `routes.py`.  

### **🔹 `models.py`**
- Definition of database tables plus some associated functions and objects

---

## 📐 Design Decisions  

- Laws are stored in the database exactly as provided by the government’s API, even if this leads to some unnecessary complexity _(e.g., `GesetzesVorhaben.beratungsstand` is an array, even though it seems to always contain a single string in practice.)_  
- The parsing that is currently done in routes.py could instead be moved to the database-level in `daily_update.py`. That would speed up requests, but make it harder to change the way laws are displayed in the future. Might consider doing this change if / when the app receives enough hits for performance to matter.

---

## 🚀 Feature Ideas  

- Improve overall visual presentation, move more of the associated data-processing into the front-end.  
- Add alert when credits on OpenRouter run low.
- Calculate statistics (e.g., average time for a law to move through legislative steps).  
  - Highlight if a law is significantly behind/ahead of schedule. Possibly use web search/AI to suggest reasons why.  
- Visualize success statistics:  
  - What percentage of laws pass, and who proposed them?  
  - Analyze based on governing party, Bundestag/Bundesrat strength at the time.  
- Possibly add  a small, horizontal timeline up top that reflects the duration of the legislative steps for the current law, as compared to the average.  
- Maybe create / replace current DIP-abstracts with AI-generated ones.
- Make links to BR-documents open the pdf on the correct page.
