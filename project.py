"""Main entry point for the QEP Comparison application."""

from interface import QEPComparisonGUI

def main():
    """Initialize and launch the desktop GUI."""

    # Create the main application window
    app = QEPComparisonGUI()

    # Start the Tkinter event loop to handle user interactions
    app.mainloop()


# Run the application only when this file is executed directly
if __name__ == "__main__":
    main()