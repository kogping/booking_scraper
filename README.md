## Setup and Installation

1.  **Install Dependencies:** Install the required Python packages using the `requirements.txt` file.
    ```bash
    pip install -r requirements.txt
    ```

---

## Running the Application

You need to run the scripts in order: first the scraper to generate the data, then the API server to serve it.

**Step 1: Run the Scraper (`scrape_booking.py`)**

*   Ensure your virtual environment is activated.
*   Make sure ChromeDriver is correctly installed and accessible (see Prerequisites).
*   Execute the scraper script from your terminal:
    ```bash
    python scrape_booking.py
    ```

**Step 2: Run the API Server (`app.py`)**

*   Ensure the scraper has successfully run and created the `booking_listings.csv` file in the project directory.
*   Ensure your virtual environment is still activated.
*   Execute the Flask app script from your terminal:
    ```bash
    python app.py
    ```
    
**Step 3: Access the API Endpoint**

*   Open your web browser or use a tool like `curl` or Postman.
*   Navigate to the following URL:
    ```
    http://localhost:5000/cheapest_listings
    ```
