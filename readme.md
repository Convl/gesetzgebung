# Gesetzgebung - A Project for Displaying Information About the Progress of German Laws

## 📌 Project Idea  
The German government provides a portal for tracking the legislative progress of laws at [dip.bundestag.de](https://dip.bundestag.de), but its presentation is **not very user-friendly**.  

By **fetching the government’s data via their API**, this project aims to provide:  
- A **more user-friendly presentation** of legislative progress.  
- **Additional features**, such as:  
  - Displaying the **remaining legislative steps** required for a law to take effect.  
  - Integrating **news articles** about a law's progress.  

---

## ⚙️ Main Functionality  

### **🔹 `daily_update.py`**  
- Retrieves **new/updated laws** from the government’s database and transfers them to our own.  
- Adds new laws to the **Elasticsearch index**.  
- At certain intervals:  
  - Searches for **news articles** about recent legislative events.  
  - Stores **top 5 articles + a summary** in the database.  

### **🔹 `routes.py`**  
- Parses **laws from the database** for display on the website.  
- **All HTML formatting** is currently done **via string manipulation** (may move this to the frontend in the future).  
- Provides a **search function** for laws using **Elasticsearch**.  

### **🔹 `helpers.py`**  
- Contains **helper functions** for parsing laws in `routes.py`.  

---

## 📐 Design Decisions  

- **Laws are stored in the database exactly as provided by the government’s API**, even if this leads to some unnecessary complexity.  
  - _(e.g., `GesetzesVorhaben.beratungsstand` is an **array**, even though it seems to always contain a **single string** in practice.)_  
- **Parsing laws (`routes.py`) could be moved to `daily_update.py`** (database-level parsing).  
  - This would **speed up requests**, but make it **harder to change the display logic** later.  
  - **Might consider this change** if/when the app gets enough traffic for performance to matter.  

---

## 🚀 Feature Ideas  

- **Improve overall visual presentation.**  
- **Calculate statistics** (e.g., average time for a law to move through legislative steps).  
  - Highlight if a law is **behind/ahead of schedule**.  
  - Possibly **use web search/AI** to suggest reasons why.  
- **Visualize success statistics**:  
  - What **percentage of laws pass**, and who proposed them?  
  - Analyze based on **governing party, Bundestag/Bundesrat strength** at the time.  
- **Add a timeline visualization**:  
  - Show **legislative step durations** for the current law vs. average.  
- **AI-generated abstracts**:  
  - Create **better summaries** than the government’s **DIP abstracts**.  
- **Improve Bundesrat (BR) document links**:  
  - Open PDFs directly **at the relevant page**.  

---

### 📢 **Next Steps**
📌 Implementing **search optimizations, performance improvements, and UI enhancements**.  
📌 Gathering **user feedback** for additional **feature requests**.  

---

**💡 Contributions & feedback are welcome!** 🚀
