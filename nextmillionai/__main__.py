import sys

from nextmillionai.build_profile import main

try:
    main()
except KeyboardInterrupt:
    # A scan can take a while on large machines; Ctrl+C should exit
    # cleanly with a reassuring note, never a scary traceback.
    print(
        "\n  Stopped. Nothing was sent anywhere — your data stayed local.",
        file=sys.stderr,
    )
    sys.exit(130)
