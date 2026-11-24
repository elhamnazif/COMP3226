from html.parser import HTMLParser
import json
import pandas as pd
import unicodedata

def StrDropWhile(s,c):
    cutoff = 0

    while(s[cutoff] != c):
        cutoff = cutoff + 1

    return s[cutoff:]

class QuantityParser(HTMLParser):
    def __init__(self):
        super().__init__()

        self.df = pd.DataFrame()

    def handle_data(self, data):
        qtys = json.loads(data)
        df = pd.DataFrame(qtys['data'])
        self.df = df[df['limitPerUser'].notna()]

    def getDFFrom(self,data):
        self.feed(data)
        return self.df

class ItemParser(HTMLParser):
    def __init__(self):
        super().__init__()

        self.df = pd.DataFrame()

    def handle_data(self, data):
        items = json.loads(data)
        df = pd.DataFrame(items['data'])
        self.df = df[df['deletedAt'].isna()]

    def preprocess(data):
        return "".join(ch for ch in StrDropWhile(data,'{') if unicodedata.category(ch) != "Cc")

    def getDFFrom(self,data):
        self.feed(data)
        return self.df

if __name__ == "__main__":

    try:
        with open("curl_qtys.txt", 'r') as f:
            qty = QuantityParser()
            qty.feed(f.read())

            print(qty.df)

        with open("curl_items.txt", 'r') as f:
            itm = ItemParser()
            itm.feed(f.read())

            print(itm.df)
    except FileNotFoundError:
        print("One or more files do not exist! Run Scrape.py first!")
