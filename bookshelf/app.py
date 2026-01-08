#!/usr/bin/env python3

import bookshelf.fuzzy
import bookshelf.util
import configparser
import os
import readline
import shutil
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass

# Enable history (optional)
readline.parse_and_bind("tab: complete")  # Enable tab completion
readline.parse_and_bind("set editing-mode vi")  # Enable Vi mode (optional)

# DataClass: Metadata ----------------------------------------------------------
@dataclass
class Metadata:
    filename: str
    title: str
    authors: str
    category: str
    keywords: str
    description: str


class Bookshelf:
    def __init__(self):
        # Configuration
        self.icon_keyboard = "\uf11c"

        self.icon_info = "\uf02d"
        self.icon_warn = "\uea6c"
        self.icon_err = "\uea87"

        # First, go with default settings.
        home_directory = os.path.expanduser("~")

        config = configparser.ConfigParser()
        config["settings"] = {
            "root_directory": f"{home_directory}/bookshelf",
            "db_filename": "_database.db",
            "table_name": "docs",
            "inbox_directory": "inbox",
            "files_directory": "files",
        }

        # Then override settings using config file.
        config_path = os.path.join(home_directory, ".config/bookshelf/config.ini")

        if os.path.exists(config_path):
            config.read(config_path)

        # Set member variables related to the configuration
        # If the root directory begins with '~', replace it with full path.
        self.root_dir = config["settings"]["root_directory"].replace(
            "~", home_directory
        )
        self.db_filename = config["settings"]["db_filename"]
        self.table_name = config["settings"]["table_name"]
        self.inbox_dir = config["settings"]["inbox_directory"]
        self.files_dir = config["settings"]["files_directory"]

        # Create directories
        bookshelf.util.mkdir(self.root_dir)
        bookshelf.util.mkdir(os.path.join(self.root_dir, self.inbox_dir))
        bookshelf.util.mkdir(os.path.join(self.root_dir, self.files_dir))

        self.conn = sqlite3.connect(os.path.join(self.root_dir, self.db_filename))
        self.cursor = self.conn.cursor()

        self.cursor.execute(f"""CREATE TABLE IF NOT EXISTS {self.table_name}
        (id TEXT PRIMARY KEY, filename TEXT, title TEXT, authors TEXT,
        category TEXT, keywords TEXT, description TEXT)""")
        self.conn.commit()

        # Setup FTS table
        bookshelf.fuzzy.setup_fts(os.path.join(self.root_dir, self.db_filename), self.table_name)
        bookshelf.fuzzy.setup_fts_triggers(os.path.join(self.root_dir, self.db_filename), self.table_name)

        self.show_banner()

    def __del__(self):
        # Close connection
        self.conn.close()

    def show_config(self):
        print(
            "--------------------------------------------------------------------------------"
        )
        print(f"{self.icon_info}  Current Configurations")
        print(f" - Root directory: {self.root_dir}")
        print(f" - DB file name: {self.db_filename}")
        print(f" - Table name: {self.table_name}")
        print(f" - Inbox directory: {self.inbox_dir}")
        print(f" - Files directory: {self.files_dir}")

    def show_banner(self):
        print("*" * 80)
        print("{:^80}".format("B O O K S H E L F"))
        print("{:^80}".format("Where your documents reside"))
        print("*" * 80)

    def show_main_menu(self):
        try:
            while True:
                print("")
                print("MAIN menu")
                answer = bookshelf.util.closed_ended_question(
                    msg=f"{self.icon_keyboard}  (a)dd, (s)earch, show (c)onfig, (h)elp, or (q)uit",
                    options=["a", "s", "c", "h", "q"],
                )
                if answer == "a":
                    self.add_interactive()
                elif answer == "s":
                    self.search_interactive()
                elif answer == "c":
                    self.show_config()
                elif answer == "h":
                    self.print_help_main_menu()
                elif answer == "q":
                    print("")
                    print("Good-Bye!")
                    print("")
                    return

        except KeyboardInterrupt:
            print("")
            return

    def print_help_main_menu(self):
        print("""
Add         - add a new document to the bookshelf database
Search      - search documents using a keyword
Show config - show current configuration of bookshelf
Quit        - quit bookshelf and exit
        """)

    def add_interactive(self):
        try:
            while True:
                print("")
                print("ADD a new document to bookshelf")
                file_path = input(
                    f"{self.icon_keyboard}  File name, or Ctrl-C to cancel: "
                )
                expanded_path = os.path.expanduser(file_path)
                if os.path.exists(expanded_path):
                    self.add_document(expanded_path)
                else:
                    print(
                        bookshelf.util.make_bold_green(f"{self.icon_err}  No such file: {file_path}")
                    )

        except KeyboardInterrupt:
            print("")

    def search_interactive(self):
        try:
            while True:
                print("")
                print("SEARCH")
                keyword = input(f"{self.icon_keyboard}  Keyword, or Ctrl-C to cancel: ")
                self.search_documents(keyword)

        except KeyboardInterrupt:
            print("")

    def edit_metadata(self, filename, field_list):
        done = False

        input_title = field_list[0]
        input_authors = field_list[1]
        input_category = field_list[2]
        input_keywords = field_list[3]
        input_description = field_list[4]

        while not done:
            print(f"{self.icon_info}  Edit metadata")
            input_title = bookshelf.util.string_input("Title", input_title)
            input_authors = bookshelf.util.string_input("Authors", input_authors)
            input_category = bookshelf.util.string_input("Category", input_category)
            input_keywords = bookshelf.util.string_input("Keywords", input_keywords)
            input_description = bookshelf.util.string_input("Description", input_description)

            print("")
            print(f"{self.icon_info}  Please verify your input")
            print(f"    Filename: {filename}")
            print(f"       Title: {input_title}")
            print(f"     Authors: {input_authors}")
            print(f"    Category: {input_category}")
            print(f"    Keywords: {input_keywords}")
            print(f" Description: {input_description}")

            if (
                bookshelf.util.closed_ended_question(
                    f"{self.icon_keyboard}  All metadata correct? [y/n]"
                )
                == "y"
            ):
                done = True

        field_list[0] = input_title
        field_list[1] = input_authors
        field_list[2] = input_category
        field_list[3] = input_keywords
        field_list[4] = input_description

    # Add a Document
    def add_document(self, filename):
        name_without_extension, ext = os.path.splitext(filename)

        # Generate new name
        new_name = f"{uuid.uuid4()}{ext}"

        # Subdirectory name
        sub_dir_name = new_name[0:2]

        # If the subdirectory does not exist, create a new one.
        sub_dir_path = os.path.join(self.root_dir, self.files_dir, sub_dir_name)
        bookshelf.util.mkdir(sub_dir_path)

        dst = os.path.join(sub_dir_path, new_name)
        # Check for duplicate name (even though it is extremely rare)
        if os.path.exists(dst):
            print("[ERROR] File already exists.")
            return

        md = self.get_metadata(new_name)
        shutil.copy(filename, dst)
        self.register_document(md)

    def register_document(self, md):
        unique_id, _ = os.path.splitext(md.filename)
        self.cursor.execute(
            f"""INSERT INTO {self.table_name}
            (id, filename, title, authors, category, keywords, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                unique_id,
                md.filename,
                md.title,
                md.authors,
                md.category,
                md.keywords,
                md.description,
            ),
        )
        self.conn.commit()

    def search_documents(self, keyword):
        fuzzy_search = False
        try:
            while True:
                search_results = self.query_documents(keyword, fuzzy_search)
                if len(search_results) == 0:
                    print(
                        bookshelf.util.make_bold_green(f"{self.icon_err}  No matching records in db")
                    )
                    return

                file_indices = self.print_search_result(keyword, search_results, fuzzy_search)
                file_index = bookshelf.util.closed_ended_question(
                    f"{self.icon_keyboard}  Index for more detail, or Ctrl-C to cancel",
                    file_indices,
                )
                record = search_results[int(file_index) - 1]
                self.show_info(record[0])
                self.get_command_for_record(record[0])

        except KeyboardInterrupt:
            print("")
            return

    def print_search_result(self, keyword, search_results, fuzzy_search):
        print("")
        print(
            "--------------------------------------------------------------------------------"
        )
        print(f"{self.icon_info}  Records found with: {keyword}")
        print(
            "--------------------------------------------------------------------------------"
        )

        file_counter = 1
        file_indices = []
        for result in search_results:
            if fuzzy_search == True:
                print(f"[{file_counter}] {result[2]}")
            else:
                print(f"[{file_counter}] {result[4]}: {result[2]}")
            file_indices = file_indices + [str(file_counter)]
            file_counter += 1

        print(
            "--------------------------------------------------------------------------------"
        )
        return file_indices

    def copy_file_to_inbox_named_as_title(self, identifier):
        record = self.get_record_with_id(identifier)
        sub_dir_name = record[1][0:2]
        src_path = os.path.join(self.root_dir, self.files_dir, sub_dir_name, record[1])
        _, ext = os.path.splitext(record[1])
        filename = bookshelf.util.make_safe_filename(record[2]) + ext
        dst_path = os.path.join(self.root_dir, self.inbox_dir, filename)
        shutil.copy(src_path, dst_path)

    def open_file(self, identifier):
        record = self.get_record_with_id(identifier)
        sub_dir_name = record[1][0:2]
        self.open_document(os.path.join(self.root_dir, self.files_dir, sub_dir_name, record[1]))

    def get_command_for_record(self, identifier):
        try:
            while True:
                answer = bookshelf.util.closed_ended_question(
                    msg=f"{self.icon_keyboard}  (o)pen, (e)dit, (d)elete, (c)opy file to inbox, (h)elp, or Ctrl-C to cancel",
                    options=["o", "e", "d", "c", "h"],
                )

                if answer == "o":
                    self.open_file(identifier)
                    return

                elif answer == "e":
                    self.edit_record(identifier)
                    return

                elif answer == "d":
                    # For safety, get confirmation
                    confirm = input(
                        bookshelf.util.make_bold_red(f"{self.icon_warn}  Please confirm with 'yes': ")
                    )
                    if confirm == "yes":
                        self.remove_document(identifier)
                        print(
                            f"{self.icon_info}  The record is deleted, and the document is moved to inbox folder."
                        )
                    else:
                        print(f"{self.icon_info}  OK, the record is NOT deleted.")
                    return

                elif answer == "c":
                    self.copy_file_to_inbox_named_as_title(identifier)
                    return

                elif answer == "h":
                    self.print_help_command_for_record()

                else:
                    continue
        except KeyboardInterrupt:
            print("")
            return

    def print_help_command_for_record(self):
        print("""
Open               - open the file with a viewer
Edit               - edit the metadata of the record
Delete             - delete the record and move the file to inbox
Copy file to inbox - copy the file to inbox
        """)

    # Query Document
    def query_documents(self, keyword, fuzzy_search):
        if fuzzy_search == True:
            return bookshelf.fuzzy.fuzzy_search_fts(os.path.join(self.root_dir, self.db_filename),
                                          self.table_name,
                                          keyword)

        self.cursor.execute(
            f"""SELECT * FROM {self.table_name} WHERE
            title LIKE ? OR
            authors LIKE ? OR
            keywords LIKE ? OR
            description LIKE ?""",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"),
        )
        return self.cursor.fetchall()

    def get_record_with_id(self, identifier):
        print(f"ID: {identifier}")
        self.cursor.execute(
            f"SELECT * FROM {self.table_name} WHERE id = ?;", (identifier,)
        )
        records = self.cursor.fetchall()
        if len(records) == 0:
            raise Exception(
                bookshelf.util.make_bold_green(f"{self.icon_err}  No record with the identifier in db")
            )

        return records[0]

    # Delete a record
    def remove_record(self, identifier):
        try:
            self.cursor.execute(
                f"DELETE FROM {self.table_name} WHERE id = ?;", (identifier,)
            )
            self.conn.commit()
            print(f"{self.icon_info}  Record deleted successfully")

        except sqlite3.Error as e:
            print(bookshelf.util.make_bold_red(f"{self.icon_err}  Failed to delete record: {e}"))

    # Remove Document from database and move to 'unclassified'
    def remove_document(self, identifier):
        record = self.get_record_with_id(identifier)
        src = os.path.join(self.root_dir, self.files_dir, record[0][0:2], record[1])
        dst = os.path.join(self.root_dir, self.inbox_dir, record[1])
        print(f"SRC: {src}")
        print(f"DST: {dst}")
        shutil.move(src, dst)

        self.remove_record(identifier)

    # Open document
    def open_document(self, filename):
        subprocess.run(["open", f"{filename}"])

    # Edit record
    def edit_record(self, identifier):
        record = self.get_record_with_id(identifier)
        metadata = [record[2], record[3], record[4], record[5], record[6]]
        self.edit_metadata(record[1], metadata)
        sql_update_query = f"""
        UPDATE {self.table_name}
        SET filename = ?, title = ?, authors = ?, category = ?, keywords = ?, description = ?
        WHERE id = ?;
        """
        data = (
            record[1],
            metadata[0],
            metadata[1],
            metadata[2],
            metadata[3],
            metadata[4],
            identifier,
        )
        self.cursor.execute(sql_update_query, data)
        self.conn.commit()

    # Show info
    def show_info(self, identifier):
        record = self.get_record_with_id(identifier)
        print(f"{self.icon_info}  Info")
        print(f"    Filename: {record[1]}")
        print(f"       Title: {record[2]}")
        print(f"     Authors: {record[3]}")
        print(f"    Category: {record[4]}")
        print(f"    Keywords: {record[5]}")
        print(f" Description: {record[6]}")

    # Get metadata interactively
    def get_metadata(self, filename):
        metadata = ["", "", "", "", ""]
        self.edit_metadata(filename, metadata)

        return Metadata(
            filename,
            metadata[0],
            metadata[1],
            metadata[2],
            metadata[3],
            metadata[4],
        )

    # Get list of categories, i.e., sub-directories excluding the 'inbox'
    def get_categories(self):
        categories = bookshelf.util.scandir(self.root_dir)
        if self.inbox_dir in categories:
            categories.remove(self.inbox_dir)
        return categories


def interactive_main():
    bookshelf = Bookshelf()
    bookshelf.show_main_menu()


def add_document(filename):
    bookshelf = Bookshelf()
    bookshelf.add_document(filename)
    bookshelf.show_main_menu()


def search_documents(keyword):
    bookshelf = Bookshelf()
    bookshelf.search_documents(keyword)
    bookshelf.show_main_menu()


def print_usage():
    print("[USAGE]")
    print("  For interactive mode: bookshelf")
    print("  For quick addition:   bookshelf add (or -a) file_name")
    print("  For quick search:     bookshelf search (or -s) keyword")
    print("  For help:             bookshelf help (or -h)")


def main():
    if len(sys.argv) == 1:
        interactive_main()
        return

    if sys.argv[1] == "add" or sys.argv[1] == "-a":
        file_path = os.path.expanduser(sys.argv[2])
        if os.path.exists(file_path):
            add_document(file_path)

    elif sys.argv[1] == "search" or sys.argv[1] == "-s":
        keyword = sys.argv[2]
        if len(keyword) > 0:
            search_documents(keyword.lower())

    elif sys.argv[1] == "help" or sys.argv[1] == "-h":
        print_usage()

    else:
        print_usage()


if __name__ == "__main__":
    main()
