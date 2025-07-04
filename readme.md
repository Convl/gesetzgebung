# Gesetzgebung - A Project for Displaying Information About the Progress of German Laws

## 📌 Project Idea  
The German government provides a portal for tracking the legislative progress of laws at [dip.bundestag.de](https://dip.bundestag.de), but its presentation is not very user-friendly.  

By fetching the government's data via their API, this project aims to provide:  
- A more user-friendly presentation of legislative progress.  
- Additional features, such as:  
  - Displaying the remaining legislative steps required for a law to take effect.  
  - Integrating news articles / news summaries about a law's progress.  
  - Answering questions about laws via retrieval-augmented generation (RAG).

---

## 🏗️ Project Architecture

### **📦 `webapp/`** - Web Application Layer
- **Thin controllers** that handle HTTP requests and responses
- **Routes**: Autocomplete search, law display, and AI chat interface
- **Focus**: User interface and request/response handling only

### **📦 `updater/`** - Daily Batch Processing
- **Automated data updates** triggered by GitHub Actions cronjob
- **Law synchronization**: Fetches new/updated laws from government API
- **Document processing**: Converts PDFs to markdown, fixes broken links to specific pages
- **News integration**: Generates search queries, collects and summarizes relevant news articles
- **Search indexing**: Maintains Elasticsearch index for law search functionality

### **📦 `logic/`** - Business Logic & Domain Functions
- **Law parsing**: Interprets legislative steps and determines remaining requirements
- **AI services**: Helper functions for querying LLMs for different types of data
- **Search functionality**: Elasticsearch-powered law search and autocomplete

### **📦 `infrastructure/`** - Technical Infrastructure
- **Configuration**: Consolidated app setup, database, and service configuration
- **Database models**: SQLAlchemy models and database utilities
- **Elasticsearch**: Search client setup and index management
- **Logging**: Centralized customized logging functionality across all modules

### **📦 `static/` & `templates/`** - Frontend Assets
- **Vanilla HTML/CSS/JS**: Basic but functional user interface
- **Timeline visualization**: Interactive display of legislative progress
- **Real-time chat**: Basic AI chat interface with streaming via SSE

---

## 🔧 Pending Design Improvements 

- Minor (= re-factoring) or major (= integrating agentic framework) rewrite of the AI-associated functionality.
- Ensure thread-safety throughout entire codebase.
- Retrieve the true result count for each law from google news and factor that in in the autocomplete route (users more likely to search for laws with lots of press coverage).
- Try vectorizing the markdown-converted Dokumente and only retrieving relevant sections when generating answers in the chat route.
- Try to refine get_news() by first retrieving titles of similar-sounding laws, then making sure the LLM is not erroneously processing news articles pertaining to those laws. 
- Try to come up with intuitive aliases for laws with unintuitive titles, possibly use those in autocomplete route.
- Implement factory function / config class

## 🚀 Feature Ideas

- Calculate statistics (e.g., average time for a law to move through legislative steps).  
  - Highlight if a law is significantly behind/ahead of schedule. Possibly use web search/AI to suggest reasons why.  
- Visualize success statistics:  
  - What percentage of laws pass, and who proposed them?  
  - Analyze based on governing party, Bundestag/Bundesrat strength at the time.  
- Possibly add a small, horizontal timeline up top that reflects the duration of the legislative steps for the current law, as compared to the average.  
- Maybe create / replace current DIP-abstracts with AI-generated ones.
- Improve overall visual presentation, move more of the associated data-processing into the front-end.  

---

## 🚀 Deployment

- **Webapp**: Flask Server hosted on Heroku
- **Database**: PostgreSQL db hosted on Supabase
- **Search**: Elasticsearch cluster hosted on Bonsaisearch
- **Automation**: GitHub Actions for daily data updates
- **AI Services**: Integration with various models through OpenRouter