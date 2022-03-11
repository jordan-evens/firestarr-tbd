import os
import urllib.request as urllib2

def download(url, to_dir='.', to_file=None):
    if to_file is None:
        to_file = os.path.basename(url)
    if not os.path.exists(to_dir):
        os.mkdir(to_dir)
    to_file = os.path.join(to_dir, to_file)
    if not os.path.exists(to_file):
        print(url)
        filedata = urllib2.urlopen(url)
        with open(to_file, 'wb') as f:
            while True:
                tmp = filedata.read(1024 * 1024)
                if not tmp:
                    break 
                f.write(tmp)
    return to_file


