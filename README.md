# bookshelf

Simple document management tool running in terminal.  This tool keeps a sqlite3
database of metadata of all the documents to facilitate fast search.

This tool is being developed for my private use, and tested on macOS only.

## Dependency

* One of the [Nerd Fonts](https://www.nerdfonts.com).
* Python modules:
    - `prompt_toolkit`

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
It automatically manages the file hierarchy; each document is copied to a sub-folder
which is named as the document's category.  If there exists another file with the
same name, it appends ` (n)` to the name of the new file with an appropriate number
`n` to avoid the duplication of the name.
Note that manual movement or renaming of the sub-folders and files ruin the integrity
of the database.

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


## Example Session

### Interactive Mode: Search and Add

```shell
❯ bookshelf.py
********************************************************************************
                              B O O K S H E L F
                          Where your documents reside
********************************************************************************

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: s

SEARCH
  Keyword, or Ctrl-C to cancel: optimization
  No matching records in db

SEARCH
  Keyword, or Ctrl-C to cancel: bloom_filter

--------------------------------------------------------------------------------
  Records found with: bloom_filter
--------------------------------------------------------------------------------
[1] paper/Bloom filter.pdf
[2] paper/Unix spell checker.pdf
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: 1
  Info
    Filename: Bloom filter.pdf
       Title: Space/Time Trade-offs in Hash Coding with Allowable Errors
     Authors: Burton H. Bloom
    Category: paper
    Keywords: bloom_filter, hash_coding
 Description: Bloom filter for efficient data storage
  (o)pen, (e)dit, (d)elete, or Ctrl-C to cancel: ^C

--------------------------------------------------------------------------------
  Records found with: bloom_filter
--------------------------------------------------------------------------------
[1] paper/Bloom filter.pdf
[2] paper/Unix spell checker.pdf
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: ^C

SEARCH
  Keyword, or Ctrl-C to cancel: ^C

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: a

ADD a new document to bookshelf
  File name, or Ctrl-C to cancel: overview - gradient descent optimization.pdf
Title []: An Overview of Gradient Descent Optimization Algorithms
Authors []: Sebastian Ruder
Category - ['paper', 'quick reference', 'booklet', 'manual', 'lecture note', 'book'] []: paper
Keywords []: optimization, gradient_descent
Description []: Overview of gradient descent optimization techniques

  Please verify your input
    Filename: overview - gradient descent optimization.pdf
       Title: An Overview of Gradient Descent Optimization Algorithms
     Authors: Sebastian Ruder
    Category: paper
    Keywords: optimization, gradient_descent
 Description: Overview of gradient descent optimization techniques
  All metadata correct? [y/n]: y

ADD a new document to bookshelf
  File name, or Ctrl-C to cancel: ^C

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: q

Bye-Bye!
```

### Quick Add

```shell
❯ bookshelf.py -a "Medical Physics - 2009 - Badal - Monte Carlo simulation using a GPU.pdf"
********************************************************************************
                              B O O K S H E L F
                          Where your documents reside
********************************************************************************
Title []: Accelerating Monte Carlo Simulations of Photon Transport in a Voxelized Geometry Using a Massively Parallel Graphics Processing Unit
Authors []: Andreu Badal, Aldo Badano
Category - ['paper', 'quick reference', 'booklet', 'manual', 'lecture note', 'book'] []: paper
Keywords []: monte_carlo_simulation, gpu, photon_transport
Description []: Utilization of GPU to accelerate Monte Carlo simulation of photon transport.

  Please verify your input
    Filename: Medical Physics - 2009 - Badal - Monte Carlo simulation using a GPU.pdf
       Title: Accelerating Monte Carlo Simulations of Photon Transport in a Voxelized Geometry Using a Massively Parallel Graphics Processing Unit
     Authors: Andreu Badal, Aldo Badano
    Category: paper
    Keywords: monte_carlo_simulation, gpu, photon_transport
 Description: Utilization of GPU to accelerate Monte Carlo simulation of photon transport.
  All metadata correct? [y/n]: y

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: q

Bye-Bye!
```

### Quick Search 

```shell
❯ bookshelf.py -s "Monte Carlo"
********************************************************************************
                              B O O K S H E L F
                          Where your documents reside
********************************************************************************

--------------------------------------------------------------------------------
  Records found with: monte carlo
--------------------------------------------------------------------------------
[1] paper/Medical Physics - 2009 - Badal - Monte Carlo simulation using a GPU.pdf
[2] paper/ISBI - 2012 - Badal - Binary tree voxel geometry to reduce memory footprint.pdf
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: 1
  Info
    Filename: Medical Physics - 2009 - Badal - Monte Carlo simulation using a GPU.pdf
       Title: Accelerating Monte Carlo Simulations of Photon Transport in a Voxelized Geometry Using a Massively Parallel Graphics Processing Unit
     Authors: Andreu Badal, Aldo Badano
    Category: paper
    Keywords: monte_carlo_simulation, gpu, photon_transport
 Description: Utilization of GPU to accelerate Monte Carlo simulation of photon transport.
  (o)pen, (e)dit, (d)elete, or Ctrl-C to cancel: ^C

--------------------------------------------------------------------------------
  Records found with: monte carlo
--------------------------------------------------------------------------------
[1] paper/Medical Physics - 2009 - Badal - Monte Carlo simulation using a GPU.pdf
[2] paper/ISBI - 2012 - Badal - Binary tree voxel geometry to reduce memory footprint.pdf
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: 2
  Info
    Filename: ISBI - 2012 - Badal - Binary tree voxel geometry to reduce memory footprint.pdf
       Title: A GPU-Optimized Binary Space Partition Structure to Accelerate The Monte Carlo Simulation of CT Projections of Voxelized Patient Models with Metal Implants
     Authors: Andreu Badal, Aldo Badano
    Category: paper
    Keywords: gpu, binary_space_partition, monte_carlo_simulation, photon_projection, metal_implant
 Description: Fast Monte Carlo simulation of photon projections on patient models with metal implants using binary space partition.
  (o)pen, (e)dit, (d)elete, or Ctrl-C to cancel: ^C

--------------------------------------------------------------------------------
  Records found with: monte carlo
--------------------------------------------------------------------------------
[1] paper/Medical Physics - 2009 - Badal - Monte Carlo simulation using a GPU.pdf
[2] paper/ISBI - 2012 - Badal - Binary tree voxel geometry to reduce memory footprint.pdf
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: ^C

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: q

Bye-Bye!
```
## TODO

* Test under Linux environment

