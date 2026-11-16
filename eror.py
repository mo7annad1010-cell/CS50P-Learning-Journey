def main():
    x = get_int("What's x? ")
    print(f"x is {x}")


def get_int(prompt):
    while True:
        try:
            print(int(input(prompt)))
        except ValueError:
            pass


main()
