from pymongo import MongoClient

# Connection config
HOST = "192.168.0.172"
PORT = 27017
DB_NAME = "seyo-development"

def extract_fields(obj, prefix, fields):
    """Recursively extract all nested field keys from a document."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "_id":
                continue
            full_key = f"{prefix}.{key}" if prefix else key
            fields.add(full_key)
            extract_fields(value, full_key, fields)
    elif isinstance(obj, list):
        for item in obj:
            extract_fields(item, prefix, fields)

def get_all_fields(collection):
    """Scan EVERY document in the collection and collect all field names."""
    fields = set()
    for doc in collection.find():
        extract_fields(doc, "", fields)
    return sorted(fields)

def main():
    print(f"Connecting to MongoDB at {HOST}:{PORT} ...")
    client = MongoClient(HOST, PORT, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    print(f"Connected!\n")

    db = client[DB_NAME]
    collections = db.list_collection_names()

    if not collections:
        print("No collections found.")
        return

    print(f"Database         : {DB_NAME}")
    print(f"Total Collections: {len(collections)}")
    print("=" * 70)

    for col_name in sorted(collections):
        collection = db[col_name]
        doc_count = collection.estimated_document_count()

        print(f"\n📁 Collection : {col_name}  ({doc_count} documents)")
        print(f"   Scanning all documents for fields...")

        fields = get_all_fields(collection)

        if fields:
            print(f"   Total Fields Found: {len(fields)}")
            print(f"   {'─' * 50}")
            for field in fields:
                print(f"     • {field}")
        else:
            print("   ⚠️  No fields found (collection may be empty).")

        print(f"   {'═' * 50}")

    client.close()
    print("\n✅ Done.")

if __name__ == "__main__":
    main()