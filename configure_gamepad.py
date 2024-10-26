import argparse
from tmenv.gamepad import TmGamepad

parser = argparse.ArgumentParser(description="Helper to configure a gamepad for tmenv")
parser.add_argument("name", metavar="name", type=str, help="Gamepad name")
args = parser.parse_args()
pad = TmGamepad(args.name)
pad.configure()
input("Press any key here to close this script ...")
print("Bye bye")