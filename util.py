import os
import uuid

# ------------------------------------------------------------------------------
#                                                              Utility routines
# ------------------------------------------------------------------------------


# This function shows a prompt expecting a single character input as the answer.
# The expected answers are given as a list, and the first can be set as the
# default answer.
# This function returns the key input as lower case letter.
def closed_ended_question(msg: str, options=["y", "n"], set_default=False):
    question = msg + (f" [{options[0]}]: " if set_default else ": ")
    options[:] = [option.lower() for option in options]
    option_str = ", ".join(options)

    while True:
        answer = input(question).lower()
        if answer in options:
            return answer

        print(f"\uf02d Answer with {option_str}")


def string_input(msg: str, default_str: str, prohibited=[]):
    while True:
        input_str = prompt(f"{msg}: ", default=default_str)
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


# Rename a file with a uuid
# This function generates a uuid and renames the file.
def rename_with_uuid(filepath):
    # Split into directory, filename, and extension
    directory, filename = os.path.split(filepath)
    name, ext = os.path.splitext(filename)

    # Generate new name
    new_name = f"{uuid.uuid4()}{ext}"

    # Construct full new path
    new_path = os.path.join(directory, new_name)

    # Rename file
    os.rename(filepath, new_path)

    return new_path

