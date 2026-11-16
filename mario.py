def main():
 print_scuare(3)


def print_scuare(size):
 for i in range(size):
  print_row(size)


def print_row(width):
 print("#"* width)


main()
