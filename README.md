# bookshelf

Simple document management tool running in terminal.  This tool keeps a sqlite3
database of metadata of all the documents to facilitate fast search.

This tool is being developed for my private use, and tested on macOS only.


## Metadata

This tool keeps the following metadata of each document:
* File name
* Title
* Authors 
* Category
* Keywords
* Description


## Addition & Removal of Document 

When adding a new document, the software asks users to input the metadata above.
Then it copies the document file into an appropriate sub-folder in the root-folder.
It automatically manage the file hierarchy and manual movement of the sub-folders
and files ruins the integrity of the database.

When an entry is removed, the metadata of the related document is deleted from
the database, and the document file is moved into `inbox` folder in the root-folder.


## Search by Keyword 

This tool looks up the keyword input in the following fields of metadata:
* Title 
* Authors 
* Keywords 
* Description 


## Configuration File 

This software looks for its configuration file in `$HOME/.config/bookshelf` directory,
whose name is `config.ini`.  Here is an example config file:
```ini
[settings]
root_directory = ~/Documents/bookshelf
db_filename = _database.db 
table_name = documents
inbox_directory = inbox
```

The default setting is as follows:
```ini
[settings]
root_directory = ~/bookshelf
db_filename = _database.db 
table_name = docs
inbox_directory = inbox
```


## TODO

* Test under Linux environment

