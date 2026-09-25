import pyodbc, pandas as pd
conn = pyodbc.connect("DRIVER={SQL Server};SERVER=10.130.1.73;DATABASE=FACTREPRDETL;UID=hcdread;PWD=hcdread@re1901;")
df = pd.read_sql("SELECT TOP 100 * FROM [dbo].[EngineAssemblyHistoryCard_Master]", conn)
print(df)