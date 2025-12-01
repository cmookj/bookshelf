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

## File Storage

When a file is added to the database, this tool generates a uuid and renames the file.
A sub-directory of which the name is the first two characters of the uuid is
created in `files_directory` in `root_directory`.  (See the section `Configuration File`
below.)  Then the renamed file is **copied** to the sub-directory.

When the user choose to copy the file to `inbox` directory in search result list,
this program creates a copy of the original file which is named as the title specified
in metadata.

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
files_directory = files
```

The default setting is as follows:
```ini
[settings]
root_directory = ~/bookshelf
db_filename = _database.db
table_name = docs
inbox_directory = inbox
files_directory = files
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
  Keyword, or Ctrl-C to cancel: bloom_filter

--------------------------------------------------------------------------------
  Records found with: bloom_filter
--------------------------------------------------------------------------------
[1] Paper: Space/time trade-offs in hash coding with allowable errors
[2] Paper: Development of a spelling list
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: 1
ID: 42f8f909-d741-4d2d-8089-782edf4516d2
  Info
    Filename: 42f8f909-d741-4d2d-8089-782edf4516d2.pdf
       Title: Space/time trade-offs in hash coding with allowable errors
     Authors: Burton H. Bloom
    Category: Paper
    Keywords: bloom_filter
 Description: Trade-offs among certain computational factors in hash coding are analyzed.  The paradigm problem considered is that of testing a series of messages one-by-one for membership in a given set of messages.  Two new hash-coding methods are examined and compared with a particular conventional hash-coding method.  The new methods are intended to reduce the amount of space required to contain the hash-coded information from that associated with conventional methods.
  (o)pen, (e)dit, (d)elete, (c)opy file to inbox, or Ctrl-C to cancel: c
ID: 42f8f909-d741-4d2d-8089-782edf4516d2

--------------------------------------------------------------------------------
  Records found with: bloom_filter
--------------------------------------------------------------------------------
[1] Paper: Space/time trade-offs in hash coding with allowable errors
[2] Paper: Development of a spelling list
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: 2
ID: e9609cc4-5934-4725-81c0-260d0f6b3ed3
  Info
    Filename: e9609cc4-5934-4725-81c0-260d0f6b3ed3.pdf
       Title: Development of a spelling list
     Authors: M. Douglas McIlroy
    Category: Paper
    Keywords: spell_checker, bloom_filter, hash_code
 Description: This paper explains how to make the word list as compact as possible, for the UNIX spelling checker, SPELL.
  (o)pen, (e)dit, (d)elete, (c)opy file to inbox, or Ctrl-C to cancel: o
ID: e9609cc4-5934-4725-81c0-260d0f6b3ed3

--------------------------------------------------------------------------------
  Records found with: bloom_filter
--------------------------------------------------------------------------------
[1] Paper: Space/time trade-offs in hash coding with allowable errors
[2] Paper: Development of a spelling list
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: ^C

SEARCH
  Keyword, or Ctrl-C to cancel: ^C

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: a

ADD a new document to bookshelf
  File name, or Ctrl-C to cancel: quadrics.pdf
  Edit metadata
Title: Surface simplification using quadric error metrics
Authors: Michael Garland, Paul S. Heckbert
Category: Paper
Keywords: triangular_mesh, quadric_error, simplification, decimation, pair_contraction
Description: A surface simplification algorithm which can rapidly produce high quality approximations of polygonal m
odels.  The algorithm uses iterative contractions of vertex pairs to simplify models and maintains surface error app
roximations using quadric matrices.  By contracting arbitrary vertex pairs, the algorithm is able to join unconnecte
d regions of models.  This can facilitate much better approximations, both visually and wih respect to geometric err
or.  To allow topological joining, the algorithm also supports non-manifold surface models.

  Please verify your input
    Filename: 7a926454-b58d-46fd-a6b2-307229d686da.pdf
       Title: Surface simplification using quadric error metrics
     Authors: Michael Garland, Paul S. Heckbert
    Category: Paper
    Keywords: triangular_mesh, quadric_error, simplification, decimation, pair_contraction
 Description: A surface simplification algorithm which can rapidly produce high quality approximations of polygonal models.  The algorithm uses iterative contractions of vertex pairs to simplify models and maintains surface error approximations using quadric matrices.  By contracting arbitrary vertex pairs, the algorithm is able to join unconnected regions of models.  This can facilitate much better approximations, both visually and wih respect to geometric error.  To allow topological joining, the algorithm also supports non-manifold surface models.
  All metadata correct? [y/n]: y

ADD a new document to bookshelf
  File name, or Ctrl-C to cancel: ^C

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: q

Good-Bye!
```

### Quick Add

```shell
❯ bookshelf.py -a ./strang-paper.pdf
********************************************************************************
                               B O O K S H E L F
                          Where your documents reside
********************************************************************************
  Edit metadata
Title: The fundamental theorem of linear algebra
Authors: Gilbert Strang
Category: Paper
Keywords: row_space, column_space, nullspace, linear_equation, least_squares_equation, orthogonal_bases, pseudoinver
se, svd
Description: This paper explains the fundamental theorem of linear algebra in four different views; linear equations
, least squares equations, orthogonal bases, and the pseudoinverse.

  Please verify your input
    Filename: 4a1dc885-562a-45bb-a294-e5b7a2dc082c.pdf
       Title: The fundamental theorem of linear algebra
     Authors: Gilbert Strang
    Category: Paper
    Keywords: row_space, column_space, nullspace, linear_equation, least_squares_equation, orthogonal_bases, pseudoinverse, svd
 Description: This paper explains the fundamental theorem of linear algebra in four different views; linear equations, least squares equations, orthogonal bases, and the pseudoinverse.
  All metadata correct? [y/n]: y

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: q

Good-Bye!
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
[1] Book: Reinforcement learning: an introduction
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel: 1
ID: d01f6596-19d9-4fe8-86e9-6c57afccef8f
  Info
    Filename: d01f6596-19d9-4fe8-86e9-6c57afccef8f.pdf
       Title: Reinforcement learning: an introduction
     Authors: Richard S. Sutton, Andrew G. Barto
    Category: Book
    Keywords: reinforcement_learning, finite_markov_decision_process, dynamic_programming, monte_carlo_method
 Description: Introduction to reinforcement learning, including basic concept and applications such as finite Markov decision processes, dynamic programming, and Monte Carlo methods.
  (o)pen, (e)dit, (d)elete, (c)opy file to inbox, or Ctrl-C to cancel:

--------------------------------------------------------------------------------
  Records found with: monte carlo
--------------------------------------------------------------------------------
[1] Book: Reinforcement learning: an introduction
--------------------------------------------------------------------------------
  Index for more detail, or Ctrl-C to cancel:

MAIN menu
  (a)dd, (s)earch, show (c)onfig, or (q)uit: q

Good-Bye!
```
## TODO

* Test under Linux environment

