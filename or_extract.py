#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import PyPDF2
from io import BytesIO
import re
import sys
import os
import urllib.parse
import openai
from dotenv import load_dotenv
from pdfminer.high_level import extract_text
from pdf2image import convert_from_bytes
import pytesseract
from PIL import Image

# load .env
load_dotenv()

# OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

def get_collection_page_link(session, company_name):
    encoded_company_name = urllib.parse.quote(company_name)
    search_url = f'https://or.justice.cz/ias/ui/rejstrik-$firma?jenPlatne=PLATNE&nazev={encoded_company_name}&polozek=50&typHledani=STARTS_WITH'
    search_response = session.get(search_url)
    if search_response.status_code != 200:
        print("Search request failed")
        return None

    search_soup = BeautifulSoup(search_response.text, 'html.parser')

    # Najít odkaz na stránku firmy
    company_page_link = None
    for link in search_soup.find_all('a', href=True):
        if 'Sbírka listin' in link.get_text():
            company_page_link = link
            break

    if not company_page_link:
        print("Company page link not found")
        return None

    company_page_url = 'https://or.justice.cz/ias/ui' + company_page_link['href'].replace('./', '/')
    return company_page_url

def get_document_page_url(session, company_page_url):
    company_page_response = session.get(company_page_url)
    if company_page_response.status_code != 200:
        print("Company page request failed")
        return None

    company_page_soup = BeautifulSoup(company_page_response.text, 'html.parser')
    tables = company_page_soup.find_all('table')
    for table in tables:
        headers = [th.get_text().strip().lower() for th in table.find_all('th')]
        if 'typ listiny' in headers and 'číslo listiny' in headers:
            for row in table.find_all('tr'):
                columns = row.find_all(['td', 'th'])
                if len(columns) > 1 and 'účetní závěrka' in columns[1].get_text().lower():
                    document_link = columns[0].find('a', href=True)
                    if document_link:
                        return 'https://or.justice.cz/ias/ui' + document_link['href'].replace('./', '/')
    return None

def get_pdf_download_link(session, document_page_url):
    document_page_response = session.get(document_page_url)
    if document_page_response.status_code != 200:
        print("Document page request failed")
        return None

    document_page_soup = BeautifulSoup(document_page_response.text, 'html.parser')

    for row in document_page_soup.find_all('tr'):
        header = row.find('th')
        if header and 'digitální podoba' in header.get_text().lower():
            link_td = row.find('td')
            if link_td:
                download_link = link_td.find('a', href=True)
                if download_link:
                    pdf_url = 'https://or.justice.cz' + download_link['href']
                    return pdf_url
    return None

def analyze_pdf_with_openai(pdf_text):
    messages = [
        {"role": "system", "content": "You are a financial data extraction assistant."},
        {"role": "user", "content": f"Extract financial data needed for EBITDA calculation from the following text:\n\n{pdf_text}\n\nPlease remove the ',' thousand separators and any blank space between digits. The result should be provided in a format A - B - C + D + E, e.g.: 5678000 - 2345000 - 1234000 + 345000 + 123000. Nothing else on the output. Don't explain anything."}
    ]
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=300,
        temperature=0.2,
    )
    result = response.choices[0].message.content.strip()
    print(f"{result}")
    return result

def calculate_ebitda(s):
    try:
        # Extrakce rovnice pomocí regulárního výrazu
        match = re.search(r'([\d\s+-]+)', s)
        if not match:
            raise ValueError("Invalid input format")

        # Získání rovnice a odstranění mezer
        equation = match.group(1).replace(' ', '')

        # Vyhodnocení rovnice
        ebitda = eval(equation)
        return ebitda
    except Exception as e:
        print(f"Error calculating EBITDA: {e}")
        return None

def extract_financial_data_from_pdf(session, pdf_url):
    response = session.get(pdf_url)
    if response.status_code != 200:
        print("PDF download failed")
        return None

    pdf_data = BytesIO(response.content)
    
    # Try extracting text using PyPDF2
    try:
        reader = PyPDF2.PdfReader(pdf_data)
        text = ''
        for page in reader.pages:
            text += page.extract_text()
        if text.strip():
            financial_data = analyze_pdf_with_openai(text)
            return financial_data
    except Exception as e:
        print(f"PyPDF2 extraction failed: {e}")
    
    # Try extracting text using pdfminer.six
    try:
        text = extract_text(pdf_data)
        if text.strip():
            financial_data = analyze_pdf_with_openai(text)
            return financial_data
    except Exception as e:
        print(f"pdfminer.six extraction failed: {e}")
    
    # Use OCR as a fallback
    try:
        images = convert_from_bytes(response.content)
        ocr_text = ''
        for image in images:
            ocr_text += pytesseract.image_to_string(image)
        if ocr_text.strip():
            financial_data = analyze_pdf_with_openai(ocr_text)
            return financial_data
    except Exception as e:
        print(f"OCR extraction failed: {e}")

    print("PDF text extraction failed using all methods.")
    return None

def main(company_name):
    with requests.Session() as session:
        company_page_url = get_collection_page_link(session, company_name)
        if not company_page_url:
            print("Company page not found")
            return

        collection_page_url = get_document_page_url(session, company_page_url)
        if not collection_page_url:
            print("Collection page not found")
            return

        pdf_url = get_pdf_download_link(session, collection_page_url)
        if not pdf_url:
            print("PDF URL not found")
            return

        financial_data = extract_financial_data_from_pdf(session, pdf_url)
        if not financial_data:
            print("Financial data extraction failed")
            return

        ebitda = calculate_ebitda(financial_data)
        if ebitda is not None:
            print(f"{ebitda}")
        else:
            print("EBITDA calculation failed")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./or_extract.py <company_name>")
    else:
        company_name = sys.argv[1]
        main(company_name)

