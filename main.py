"""Entry point for ARIA_CLEAN demo project.
Run as a simple CLI for now.
"""

import argparse


def main():
    parser = argparse.ArgumentParser(description="ARIA_CLEAN demo entry")
    parser.add_argument("--serve", action="store_true", help="Launch demo UI (not implemented)")
    args = parser.parse_args()

    if args.serve:
        print("Starting demo UI... (not implemented)")
    else:
        print("ARIA_CLEAN scaffold ready.")


if __name__ == "__main__":
    main()
