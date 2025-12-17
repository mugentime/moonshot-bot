"""View Global TP Tracker Report"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tp_tracker import tp_tracker

if __name__ == "__main__":
    tp_tracker.print_report()
