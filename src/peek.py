# Taking a quick look at what landed in the database.
import duckdb

from src.config import DB_PATH

con = duckdb.connect(str(DB_PATH), read_only=True)

print(con.execute("SHOW ALL TABLES").fetchdf())
print()
print(con.execute("SELECT * FROM raw.orders LIMIT 5").fetchdf())
print()
print(con.execute("DESCRIBE raw.orders").fetchdf())

con.close()