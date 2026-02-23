try:
    import board
    print("SUCCESS: board imported")
    print("I2C bus:", board.I2C())
except ImportError as e:
    print("FAILED to import board:", e)
except Exception as e:
    print("Other error:", e)