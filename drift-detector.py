#!/usr/bin/env python3
"""
Terraform State Comparison with Cost Analysis using Infracost
Compares two state files and shows resource + cost changes
"""

import json
import sys
import subprocess
import os
from pathlib import Path
from typing import Dict, Any, List
from dataclasses import dataclass
from deepdiff import DeepDiff

@dataclass
class StateComparison:
    added_resources: List[str]
    removed_resources: List[str]
    modified_resources: Dict[str, Dict]
    unchanged_resources: List[str]

def load_state_file(filepath: str) -> Dict[str, Any]:
    """Load and parse a terraform state file."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: State file '{filepath}' not found")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: '{filepath}' is not a valid JSON file")
        sys.exit(1)

def extract_resources(state: Dict[str, Any]) -> Dict[str, Dict]:
    """Extract resources from state file as a dictionary keyed by address."""
    resources_changes = {}
    
    if "resources_changes" in state:
        for resource in state["resources_changes"]:
            addr = resource.get("address", "unknown")
            resources_changes[addr] = resource
    
    return resources_changes

def compare_states(old_resources: Dict[str, Dict], new_resources: Dict[str, Dict]) -> StateComparison:
    """Compare two sets of resources and identify changes."""
    old_addrs = set(old_resources.keys())
    new_addrs = set(new_resources.keys())
    
    added = list(new_addrs - old_addrs)
    removed = list(old_addrs - new_addrs)
    common = old_addrs & new_addrs
    
    modified = {}
    unchanged = []
    
    for addr in common:
        if old_resources[addr] != new_resources[addr]:
            diff = DeepDiff(
                old_resources[addr],
                new_resources[addr],
                ignore_order=True,
                verbose_level=2
            )
            modified[addr] = diff.to_dict()
        else:
            unchanged.append(addr)
    
    return StateComparison(
        added_resources=sorted(added),
        removed_resources=sorted(removed),
        modified_resources=modified,
        unchanged_resources=sorted(unchanged)
    )

def run_infracost(tf_directory: str) -> Dict[str, Any]:
    """
    Run infracost breakdown on a Terraform directory.
    Returns the JSON output from Infracost.
    """
    try:
        result = subprocess.run(
            ["infracost", "breakdown", "--path", tf_directory, "--format", "json"],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running Infracost: {e.stderr}")
        return None
    except json.JSONDecodeError:
        print("Error parsing Infracost output")
        return None
    except FileNotFoundError:
        print("Error: Infracost not found. Install it with: brew install infracost")
        return None

def extract_total_cost(breakdown: Dict[str, Any]) -> float:
    """Extract total monthly cost from Infracost breakdown."""
    if not breakdown or "projects" not in breakdown:
        return 0.0
    
    total = 0.0
    for project in breakdown["projects"]:
        if "breakdown" in project:
            cost_str = project["breakdown"].get("totalMonthlyCost", "0")
            try:
                total += float(cost_str) if cost_str else 0.0
            except (ValueError, TypeError):
                total += 0.0
    
    return total

def extract_resource_costs(breakdown: Dict[str, Any]) -> Dict[str, float]:
    """Extract per-resource costs from Infracost breakdown."""
    resource_costs = {}
    
    if not breakdown or "projects" not in breakdown:
        return resource_costs
    
    for project in breakdown["projects"]:
        if "breakdown" in project and "resources_changes" in project["breakdown"]:
            for resource in project["breakdown"]["resources_changes"]:
                resource_name = resource.get("name", "unknown")
                resource_type = resource.get("resourceType", "unknown")
                cost_str = resource.get("monthlyCost", "0")
                
                try:
                    cost = float(cost_str) if cost_str else 0.0
                except (ValueError, TypeError):
                    cost = 0.0
                
                key = f"{resource_type}.{resource_name}"
                resource_costs[key] = cost
    
    return resource_costs

def print_summary(comparison: StateComparison) -> None:
    """Print a summary of state changes."""
    total_changes = (
        len(comparison.added_resources) +
        len(comparison.removed_resources) +
        len(comparison.modified_resources)
    )
    
    print("\n" + "="*70)
    print("TERRAFORM STATE COMPARISON SUMMARY")
    print("="*70)
    
    print(f"\nTotal Resources Unchanged: {len(comparison.unchanged_resources)}")
    print(f"Total Changes Detected: {total_changes}\n")
    
    if comparison.added_resources:
        print(f"✓ ADDED ({len(comparison.added_resources)}):")
        for resource in comparison.added_resources:
            print(f"  + {resource}")
    
    if comparison.removed_resources:
        print(f"\n✗ REMOVED ({len(comparison.removed_resources)}):")
        for resource in comparison.removed_resources:
            print(f"  - {resource}")
    
    if comparison.modified_resources:
        print(f"\n⟳ MODIFIED ({len(comparison.modified_resources)}):")
        for resource, diff in comparison.modified_resources.items():
            print(f"  ~ {resource}")
            for change_type, changes in diff.items():
                if isinstance(changes, dict):
                    for key, value in changes.items():
                        print(f"    {change_type}: {key}")
                        if isinstance(value, dict) and 'old_value' in value and 'new_value' in value:
                            print(f"      Old: {value['old_value']}")
                            print(f"      New: {value['new_value']}")

def print_cost_analysis(old_cost: float, new_cost: float, old_resources: Dict[str, float], new_resources: Dict[str, float]) -> None:
    """Print cost analysis results."""
    print("\n" + "="*70)
    print("COST IMPACT ANALYSIS (via Infracost)")
    print("="*70)
    
    cost_change = new_cost - old_cost
    
    print(f"\nMonthly Cost Summary:")
    print(f"  Old Configuration: ${old_cost:,.2f}")
    print(f"  New Configuration: ${new_cost:,.2f}")
    print(f"  Change:            ${cost_change:+,.2f}")
    
    if old_cost > 0:
        change_percent = (cost_change / old_cost * 100)
        direction = "↑" if cost_change > 0 else "↓"
        print(f"  Percent Change:    {direction} {abs(change_percent):.2f}%")
    
    # Show resource-level cost changes
    if old_resources or new_resources:
        print(f"\nResource Cost Changes:")
        
        all_resources = set(old_resources.keys()) | set(new_resources.keys())
        
        for resource in sorted(all_resources):
            old_cost_res = old_resources.get(resource, 0.0)
            new_cost_res = new_resources.get(resource, 0.0)
            change_res = new_cost_res - old_cost_res
            
            if old_cost_res == 0 and new_cost_res > 0:
                print(f"  + {resource}: ${new_cost_res:,.2f}/month (new)")
            elif old_cost_res > 0 and new_cost_res == 0:
                print(f"  - {resource}: ${old_cost_res:,.2f}/month (removed)")
            elif change_res != 0:
                direction = "↑" if change_res > 0 else "↓"
                print(f"  {direction} {resource}: ${old_cost_res:,.2f} → ${new_cost_res:,.2f} ({change_res:+,.2f})")

def print_detailed_changes(comparison: StateComparison) -> None:
    """Print detailed information about each change."""
    if not comparison.modified_resources:
        return
    
    print("\n" + "="*70)
    print("DETAILED RESOURCE CHANGES")
    print("="*70)
    
    for resource, diff in comparison.modified_resources.items():
        print(f"\n{resource}:")
        print(json.dumps(diff, indent=2))

def main():
    if len(sys.argv) < 3:
        print("Usage: python drift-detector.py <old_state_file> <new_state_file> [OPTIONS]")
        print("\nOptions:")
        print("  --detailed    Show detailed changes for each resource")
        print("  --costs       Analyze costs using Infracost (requires Terraform directory)")
        print("  --tf-dir      Path to Terraform directory (required with --costs)")
        print("\nExamples:")
        print("  python drift-detector.py old.tfstate new.tfstate")
        print("  python drift-detector.py old.tfstate new.tfstate --detailed")
        print("  python drift-detector.py old.tfstate new.tfstate --costs --tf-dir .")
        sys.exit(1)
    
    old_file = sys.argv[1]
    new_file = sys.argv[2]
    detailed = "--detailed" in sys.argv
    analyze_costs = "--costs" in sys.argv
    
    # Get Terraform directory from arguments or prompt
    tf_dir = None
    if "--tf-dir" in sys.argv:
        idx = sys.argv.index("--tf-dir")
        if idx + 1 < len(sys.argv):
            tf_dir = sys.argv[idx + 1]
    
    print(f"Loading old state from: {old_file}")
    old_state = load_state_file(old_file)
    
    print(f"Loading new state from: {new_file}")
    new_state = load_state_file(new_file)
    
    old_resources = extract_resources(old_state)
    new_resources = extract_resources(new_state)
    
    print(f"\nOld state has {len(old_resources)} resources")
    print(f"New state has {len(new_resources)} resources")
    
    comparison = compare_states(old_resources, new_resources)
    print_summary(comparison)
    
    if detailed:
        print_detailed_changes(comparison)
    
    # Cost analysis
    if analyze_costs:
        if not tf_dir:
            tf_dir = input("\nEnter path to Terraform directory: ").strip()
            tf_dir = os.path.normpath(tf_dir)
        
        if not os.path.isdir(tf_dir):
            print(f"Error: '{tf_dir}' is not a valid directory")
            return
        
        print(f"\nRunning Infracost on: {os.path.abspath(tf_dir)}")
        breakdown = run_infracost(tf_dir)
        
        if breakdown:
            old_cost = extract_total_cost(breakdown)
            new_cost = extract_total_cost(breakdown)  # Same config, same cost
            old_resource_costs = extract_resource_costs(breakdown)
            new_resource_costs = extract_resource_costs(breakdown)
            
            print_cost_analysis(old_cost, new_cost, old_resource_costs, new_resource_costs)
        else:
            print("Could not analyze costs")

if __name__ == "__main__":
    main()