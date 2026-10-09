BUS_FILE = "data/busStop.csv"
SCHOOL_FILE = "data/locations.csv"
STUDENT_FILE = "data/Innlandets.csv"

# ---- Time limits (seconds) -------------------------------------------------
# Total solve time for one run (column generation + branch-and-price + final
# integer model, or the MILP). None = no limit. Data loading is not counted.
TIME_LIMIT = 3600
# Part of TIME_LIMIT kept back for the final integer model over the column
# pool, so a run that hits the limit still returns a feasible solution.
FINAL_MODEL_RESERVE = 60
# Upper limit for a single exact pricing call (also capped by TIME_LIMIT).
PRICING_TIME_LIMIT = 600
