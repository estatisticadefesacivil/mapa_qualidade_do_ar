import pandas as pd

url = "https://office365prodam-my.sharepoint.com/personal/estatistica_analisededados_defesacivil_am_gov_br/Documents/sensores_amazonas.xlsx?web=1"

df = pd.read_excel(url)

print(df.head())  # Verifica se está funcionando
