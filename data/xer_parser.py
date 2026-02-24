import os 
from xer_reader import XerReader
from glob import glob

class XERParser:
    def __init__(self, xer_file_path):
        self.xer_file_path = xer_file_path
        self.export_dir = "data/exports"
        if not os.path.exists(self.export_dir):
            os.makedirs(self.export_dir)

    def parse(self):
        if not os.path.exists(self.xer_file_path):
            raise FileNotFoundError(f"XER file not found: {self.xer_file_path}")
        
        files = glob(os.path.join(self.xer_file_path, "*.xer"))
        for file in files:
            reader = XerReader(file)
            reader.to_csv(self.export_dir, delimeter=",")
    

if __name__ == "__main__":
    xer_file_path = "data/"
    parser = XERParser(xer_file_path)
    data = parser.parse()