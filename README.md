# 🗺️ Google Maps Scraper (Streamlit + Playwright + Python)

A **Streamlit web app** to scrape business details from **Google Maps** using **Playwright automation**.  
It extracts clean, structured data from Google Maps listings and lets you **download results** as Excel & CSV.

---

## 🚀 Features
- Enter a **Google Maps search query** (e.g., `dentists in Karachi`) or a **full Maps URL**
- Automatically scrolls & loads multiple result pages
- Extracts details:
  - Business name
  - Address (city, zip code, country)
  - Phone number
  - Website
  - Reviews (average rating + total count)
  - Categories
  - Opening hours (Mon–Sun)
  - Latitude & Longitude
  - Social links (Instagram, Facebook, LinkedIn, X/Twitter)
- Live results in the Streamlit app
- **Download results** (Excel with bold headers or CSV)
- **Stop button** to end scraping anytime
- Works in **headless** (hidden) or **visible** browser mode

---

## 🛠️ Technologies Used
- **Python 3.10+**
- [Streamlit](https://streamlit.io/) – user interface
- [Playwright](https://playwright.dev/python/) – browser automation
- [Pandas](https://pandas.pydata.org/) – data handling
- [OpenPyXL](https://openpyxl.readthedocs.io/) – Excel export
- [Requests](https://docs.python-requests.org/) + Regex – social links extraction

---

## 📖 How to Use

 - Enter a Google Maps search query or full URL
 - Adjust settings from the sidebar:
     - Run headless (on/off)
     - Use system Chrome (optional)
     - Max listings (0 = unlimited)
     - Scroll delay per listing
  - Click ▶️ Start to scrape
  - See live logs and results
  - Click 🛑 Stop anytime
  - Download data in Excel/CSV

---

## 🧪 Example:
  - Search: restaurants in London
  - Output:
      - Restaurant names
      - Addresses with city/zip/country
      - Phone numbers & websites
      - Reviews (ratings & counts)
      - Opening hours
   
---

## 🔧 Troubleshooting:
  - ❌ Browser not launching → disable headless mode.
  - ❌ Playwright errors → run playwright install chromium.
  - ❌ No results → try a full URL instead of short query.
  - ❌ Duplicates → already handled by script

---

## 📌 Disclaimer:
  - ⚠️ This tool is for educational/demo purposes only.
  - Please respect Google’s Terms of Service and your local laws.

## 👨‍💻 Credits:
  -  Developer: **SYED IRTIZA ABBAS ZAIDI**
  -  Built with ❤️ using Python, Streamlit & Playwright

