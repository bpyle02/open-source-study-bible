import requests
import gzip
import json
import time

BASE_URL = "https://bible.helloao.org/api/c/matthew-henry"

def fetch_books():
    """Fetches the list of books from the API."""
    print(f"Fetching books from {BASE_URL}/books.json...")
    response = requests.get(f"{BASE_URL}/books.json")
    response.raise_for_status()
    
    # The API might return a direct list or a dictionary containing a list.
    data = response.json()
    if isinstance(data, dict) and "books" in data:
        return data["books"]
    return data

def fetch_chapters_for_book(book_id):
    """Fetches all chapters for a given book ID until a 404 is encountered."""
    chapters = []
    chapter_num = 1
    
    while True:
        url = f"{BASE_URL}/{book_id}/{chapter_num}.json"
        response = requests.get(url)
        
        # If we hit a 404, we've reached the end of the chapters for this book
        if response.status_code == 404:
            break
            
        # If there's another error, raise it
        response.raise_for_status()
        
        print(f"  Fetched {book_id} Chapter {chapter_num}")
        chapter_data = response.json()
        
        # Store the chapter data, optionally adding metadata so we know where it came from
        chapters.append({
            "book_id": book_id,
            "chapter": chapter_num,
            "data": chapter_data
        })
        
        chapter_num += 1
        
        # Be polite to the API by adding a small delay
        time.sleep(0.1)
        
    return chapters

def main():
    books_data = fetch_books()
    all_chapters = []
    
    for book in books_data:
        # Depending on the API's exact JSON structure, the book identifier 
        # might be under 'id', 'book_id', 'slug', etc. 'id' is standard.
        book_id = book.get("id") or book.get("slug")
        
        if not book_id:
            print(f"Skipping a book without a recognizable ID: {book}")
            continue
            
        print(f"\nProcessing book: {book_id}")
        book_chapters = fetch_chapters_for_book(book_id)
        all_chapters.extend(book_chapters)

    # Construct the final unified dictionary
    final_data = {
        "books": books_data,
        "chapters": all_chapters
    }

    # Save to a compressed json.gz file
    output_filename = "matthew_henry_commentary.json.gz"
    print(f"\nCompressing and saving data to {output_filename}...")
    
    # Write the JSON data as a UTF-8 encoded byte string to a gzip file
    with gzip.open(output_filename, 'wt', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
        
    print("Done!")

if __name__ == "__main__":
    main()