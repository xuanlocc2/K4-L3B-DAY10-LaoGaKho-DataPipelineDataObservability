import chromadb
client = chromadb.PersistentClient(path='data/chroma')
for name in ['papers-baseline', 'papers-live', 'papers-corrupted', 'papers-repaired']:
    try:
        c = client.get_collection(name)
        print(name + ': ' + str(c.count()) + ' docs')
    except Exception as e:
        print(name + ': ERROR ' + str(e))
