import requests
import gzip
import json
import time

BASE_URL = "https://bible.helloao.org/api"
TRANSLATIONS = ["ENGWEBP", "KJV"]

def fetch_books(translation_id):
    """Fetches the list of books for a given translation."""
    url = f"{BASE_URL}/{translation_id}/books.json"
    print(f"Fetching books for {translation_id} from {url}...")
    response = requests.get(url)
    response.raise_for_status()
    
    data = response.json()
    # The API returns a dictionary with a 'books' array for translations
    if isinstance(data, dict) and "books" in data:
        return data["books"]
    return data

def fetch_chapters_for_book(translation_id, book):
    """Fetches all chapters for a given book using its numberOfChapters property."""
    book_id = book["id"]
    num_chapters = book.get("numberOfChapters", 0)
    chapters = []
    
    # We know exactly how many chapters to fetch based on the books.json metadata
    for chapter_num in range(1, num_chapters + 1):
        url = f"{BASE_URL}/{translation_id}/{book_id}/{chapter_num}.json"
        response = requests.get(url)
        
        # Fallback safety: just in case the metadata count is off
        if response.status_code == 404:
            print(f"  Warning: {book_id} Chapter {chapter_num} returned 404. Stopping book early.")
            break
            
        response.raise_for_status()
        
        print(f"  Fetched {translation_id} - {book_id} Chapter {chapter_num}/{num_chapters}")
        chapter_data = response.json()
        
        chapters.append({
            "book_id": book_id,
            "chapter": chapter_num,
            "data": chapter_data
        })
        
        # 50ms delay to be polite to the API server
        time.sleep(0.05)
        
    return chapters

def process_translation(translation_id):
    """Processes an entire translation and saves it to a gzipped JSON file."""
    print(f"\n{'='*40}")
    print(f"Processing Translation: {translation_id}")
    print(f"{'='*40}")
    
    books_data = fetch_books(translation_id)
    all_chapters = []
    
    for book in books_data:
        book_id = book.get("id")
        if not book_id:
            continue
            
        book_chapters = fetch_chapters_for_book(translation_id, book)
        all_chapters.extend(book_chapters)

    # Structure the final JSON payload
    final_data = {
        "translation_id": translation_id,
        "books": books_data,
        "chapters": all_chapters
    }

    # Compress and save to its own specific file (e.g., bsb_translation.json.gz)
    output_filename = f"{translation_id.lower()}_translation.json.gz"
    print(f"\nCompressing and saving {translation_id} data to {output_filename}...")
    
    with gzip.open(output_filename, 'wt', encoding='utf-8') as f:
        # Avoiding indent=2 to heavily optimize the resulting file size
        json.dump(final_data, f, ensure_ascii=False)
        
    print(f"Finished {translation_id}! Saved to {output_filename}.")

def main():
    # Loop through the requested translations and run the fetcher for each
    for translation_id in TRANSLATIONS:
        try:
            process_translation(translation_id)
        except requests.exceptions.RequestException as e:
            print(f"A network error occurred while processing {translation_id}: {e}")
        except Exception as e:
            print(f"An unexpected error occurred while processing {translation_id}: {e}")

if __name__ == "__main__":
    main()