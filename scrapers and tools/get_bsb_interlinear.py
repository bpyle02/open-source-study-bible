import requests
import gzip
import json
import time

# Note the '/d/' in the path instead of '/c/' for datasets
BASE_URL = "https://bible.helloao.org/api/d/bsb-interlinear"

def fetch_books():
    """Fetches the list of books from the interlinear API."""
    print(f"Fetching books from {BASE_URL}/books.json...")
    response = requests.get(f"{BASE_URL}/books.json")
    response.raise_for_status()
    
    data = response.json()
    # Handle both { "books": [...] } and direct array responses
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
        
        # 404 means we've reached the end of the book
        if response.status_code == 404:
            break
            
        response.raise_for_status()
        
        print(f"  Fetched {book_id} Chapter {chapter_num}")
        chapter_data = response.json()
        
        # Add metadata so you know which book/chapter this data belongs to in the flat list
        chapters.append({
            "book_id": book_id,
            "chapter": chapter_num,
            "data": chapter_data
        })
        
        chapter_num += 1
        
        # 100ms delay to be polite to the API server
        time.sleep(0.1)
        
    return chapters

def main():
    print(f"hello!")
    books_data = fetch_books()
    all_chapters = []

    
    for book in books_data:
        # Standard ID key is usually 'id' (e.g., 'GEN', 'EXO')
        book_id = book.get("id")
        
        if not book_id:
            print(f"Skipping a book without a recognizable ID: {book}")
            continue
            
        print(f"\nProcessing book: {book_id} ({book.get('name', 'Unknown Name')})")
        book_chapters = fetch_chapters_for_book(book_id)
        all_chapters.extend(book_chapters)

    # Structure the final JSON payload
    final_data = {
        "books": books_data,
        "chapters": all_chapters
    }

    # Compress and save
    output_filename = "bsb_interlinear.json.gz"
    print(f"\nCompressing and saving data to {output_filename}...")
    
    with gzip.open(output_filename, 'wt', encoding='utf-8') as f:
        # indent=None saves space in the final file compared to indent=2
        json.dump(final_data, f, ensure_ascii=False)
        
    print(f"Done! Successfully saved {len(books_data)} books and {len(all_chapters)} chapters.")

if __name__ == "__main__":
    main()