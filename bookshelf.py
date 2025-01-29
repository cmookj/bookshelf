#!/usr/bin/env python3

import configparser
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass


# ------------------------------------------------------------------------------
#                                                              Utility routines
# ------------------------------------------------------------------------------


# This function shows a prompt expecting a single character input as the answer.
# The expected answers are given as a list, and the first can be set as the
# default answer.
# This function returns the key input as lower case letter.
def closed_ended_question(msg: str, options=["y", "n"], set_default=False):
    prompt = msg + (f" [{options[0]}]: " if set_default else ": ")
    options[:] = [option.lower() for option in options]
    option_str = ", ".join(options)

    while True:
        answer = input(prompt).lower()
        if answer in options:
            return answer

        print(f"\uf02d Answer with {option_str}")


def string_input(msg: str, default_str: str, prohibited=[]):
    while True:
        input_str = input(msg + f" [{default_str}]: ")
        if input_str in prohibited:
            print("\uea87  Invalid (prohibited) input data")
            continue

        if len(input_str) == 0:
            return default_str

        return input_str


# Make a new directory if there is none
def mkdir(dir):
    if os.path.exists(dir):
        return
    os.mkdir(dir)


# Get the list of all directoriees
def scandir(dir):
    directories = [entry.name for entry in os.scandir(dir) if entry.is_dir()]
    return directories


# Make text in bold face, red color
def make_bold_red(text: str):
    return f"\033[1;31m{text}\033[0m"


# Make text in bold face, green color
def make_bold_green(text: str):
    return f"\033[1;32m{text}\033[0m"


# Get unique file name
# This function checks whether there exists another file with the name given.
# If there is one, this function appends '(n)' to the file name where 'n'
# increases until there is no duplicate name.
# Otherwise, this function returns the name given as is.
def unique_filename(dir: str, filename: str, ext: str) -> str:
    if not os.path.exists(dir):
        raise Exception(f"\uea87  Directory {dir} does not exist")

    if not os.path.exists(dir + "/" + filename + ext):
        return filename

    counter = 1
    while os.path.exists(dir + "/" + filename + f" ({counter}){ext}"):
        counter += 1

    return filename + f" ({counter})"


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
        }

        # Then override settings using config file.
        config_path = f"{home_directory}/.config/bookshelf/config.ini"

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

        self.conn = sqlite3.connect(f"{self.root_dir}/{self.db_filename}")
        self.cursor = self.conn.cursor()

        self.cursor.execute(f"""CREATE TABLE IF NOT EXISTS {self.table_name} 
        (id TEXT PRIMARY KEY, filename TEXT, title TEXT, authors TEXT,
        category TEXT, keywords TEXT, description TEXT)""")
        self.conn.commit()

        mkdir(f"{self.root_dir}/{self.inbox_dir}")

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

    def show_banner(self):
        print(
            "********************************************************************************"
        )
        print("                              B O O K S H E L F")
        print("                          Where your documents reside")
        print(
            "********************************************************************************"
        )

    def show_main_menu(self):
        try:
            while True:
                print("")
                print("MAIN menu")
                answer = closed_ended_question(
                    msg=f"{self.icon_keyboard}  (a)dd, (s)earch, show (c)onfig, or (q)uit",
                    options=["a", "s", "c", "q"],
                )
                if answer == "a":
                    self.add_interactive()
                elif answer == "s":
                    self.search_interactive()
                elif answer == "c":
                    self.show_config()
                elif answer == "q":
                    print("")
                    print("Bye-Bye!")
                    print("")
                    return

        except KeyboardInterrupt:
            print("")
            return

    def add_interactive(self):
        try:
            while True:
                print("")
                print("ADD a new document to bookshelf")
                file_path = input(
                    f"{self.icon_keyboard}  File name, or Ctrl-C to cancel: "
                )
                if os.path.exists(file_path):
                    self.add_document(file_path)
                else:
                    print(
                        make_bold_green(f"{self.icon_err}  No such file: {file_path}")
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
            categories = self.get_categories()

            input_title = string_input("Title", input_title)
            input_authors = string_input("Authors", input_authors)
            input_category = string_input(
                f"Category - {categories}", input_category, ["inbox"]
            )
            input_keywords = string_input("Keywords", input_keywords)
            input_description = string_input("Description", input_description)

            print("")
            print(f"{self.icon_info}  Please verify your input")
            print(f"    Filename: {filename}")
            print(f"       Title: {input_title}")
            print(f"     Authors: {input_authors}")
            print(f"    Category: {input_category}")
            print(f"    Keywords: {input_keywords}")
            print(f" Description: {input_description}")

            if (
                closed_ended_question(
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
        md = self.get_metadata(filename)
        categories = self.get_categories()
        if md.category not in categories:
            os.mkdir(self.root_dir + f"/{md.category}")

        name_without_extension, extension = os.path.splitext(filename)
        md.filename = (
            unique_filename(
                self.root_dir + f"/{md.category}",
                name_without_extension,
                extension,
            )
            + f"{extension}"
        )
        dst = self.root_dir + f"/{md.category}/" + md.filename
        shutil.copy(filename, dst)
        self.register_document(md)

    def register_document(self, md):
        unique_id = str(uuid.uuid4())
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
        try:
            while True:
                search_results = self.query_documents(keyword)
                if len(search_results) == 0:
                    print(
                        make_bold_green(f"{self.icon_err}  No matching records in db")
                    )
                    return

                file_indices = self.print_search_result(keyword, search_results)
                file_index = closed_ended_question(
                    f"{self.icon_keyboard}  Index for more detail, or Ctrl-C to cancel",
                    file_indices,
                )
                record = search_results[int(file_index) - 1]
                self.show_info(record[0])
                self.get_command_for_record(record[0])

        except KeyboardInterrupt:
            print("")
            return

    def print_search_result(self, keyword, search_results):
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
            print(f"[{file_counter}] {result[4]}/{result[1]}")
            file_indices = file_indices + [str(file_counter)]
            file_counter += 1

        print(
            "--------------------------------------------------------------------------------"
        )
        return file_indices

    def get_command_for_record(self, identifier):
        try:
            while True:
                answer = closed_ended_question(
                    msg=f"{self.icon_keyboard}  (o)pen, (e)dit, (d)elete, or Ctrl-C to cancel",
                    options=["o", "e", "d"],
                )
                if answer == "o":
                    record = self.get_record_with_id(identifier)
                    self.open_document(self.root_dir + f"/{record[4]}/{record[1]}")
                    return
                elif answer == "e":
                    self.edit_record(identifier)
                    return
                elif answer == "d":
                    # For safety, get confirmation
                    confirm = input(
                        make_bold_red(f"{self.icon_warn}  Please confirm with 'yes': ")
                    )
                    if confirm == "yes":
                        self.remove_document(identifier)
                        print(
                            f"{self.icon_info}  The record is deleted, and the document is moved to inbox folder."
                        )
                    else:
                        print(f"{self.icon_info}  OK, the record is NOT deleted.")
                    return
                else:
                    continue
        except KeyboardInterrupt:
            print("")
            return

    # Query Document
    def query_documents(self, keyword):
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
        self.cursor.execute(
            f"SELECT * FROM {self.table_name} WHERE id = ?;", (identifier,)
        )
        records = self.cursor.fetchall()
        if len(records) == 0:
            raise Exception(
                make_bold_green(f"{self.icon_err}  No record with the identifier in db")
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
            print(make_bold_red(f"{self.icon_err}  Failed to delete record: {e}"))

    # Remove Document from database and move to 'unclassified'
    def remove_document(self, identifier):
        record = self.get_record_with_id(identifier)
        src = self.root_dir + f"/{record[4]}/{record[1]}"
        dst = self.root_dir + f"/{self.inbox_dir}/{record[1]}"
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
        categories = scandir(self.root_dir)
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
        file_path = sys.argv[2]
        if os.path.exists(file_path):
            add_document(sys.argv[2])

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
