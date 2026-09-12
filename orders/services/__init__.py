"""Framework-agnostic services backing the orders app.

Currently only the thermal-printing stack lives here: :mod:`receipts` composes
the ESC/POS byte stream and :mod:`printer` delivers it to the hardware. Both
were ported from the sibling Okinawa POS project, where they have been running
in production, so they stay deliberately free of Django model knowledge beyond
the little the ticket composer needs.
"""
