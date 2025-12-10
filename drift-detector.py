#!/usr/bin/env python3
"""
Terraform State vs Plan Comparison with Nested Change Detection
Compares applied state file to planned changes and shows ALL modifications
"""

import json
import sys
import subprocess
import os
from pathlib import Path
from typing import Dict, Any, List, Tuple, Set
from dataclasses import dataclass
from deepdiff import DeepDiff

@dataclass
class ResourceChange:
    """Represents a single resource change"""
    address: str
    action: str  # 'create', 'update', 'delete', 'no-op'
    before: Dict[str, Any]
    after: Dict[str, Any]
    detailed_changes: Dict[str, Any]

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

def load_plan_file(filepath: str) -> Dict[str, Any]:
    """Load and parse a terraform plan file (JSON format)."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Plan file '{filepath}' not found")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: '{filepath}' is not a valid JSON file")
        sys.exit(1)

def extract_state_resources(state: Dict[str, Any]) -> Dict[str, Dict]:
    """
    Extract resources from state file.
    Returns dict with resource address as key and full resource object as value.
    """
    resources = {}
    
    # State files have a "resources" key containing all resources
    if "resources" in state:
        for resource in state["resources"]:
            resource_type = resource.get("type", "unknown")
            resource_name = resource.get("name", "unknown")
            
            # Full address is like "aws_security_group.web"
            address = f"{resource_type}.{resource_name}"
            
            # Include instances if they exist
            if "instances" in resource:
                for idx, instance in enumerate(resource["instances"]):
                    instance_addr = address if idx == 0 else f"{address}[{idx}]"
                    resources[instance_addr] = {
                        "type": resource_type,
                        "name": resource_name,
                        "attributes": instance.get("attributes", {}),
                        "private": instance.get("private", {})
                    }
            else:
                resources[address] = {
                    "type": resource_type,
                    "name": resource_name,
                    "attributes": resource.get("instances", [{}])[0].get("attributes", {}) if resource.get("instances") else {}
                }
    
    return resources

def extract_plan_changes(plan: Dict[str, Any]) -> List[ResourceChange]:
    """
    Extract resource changes from plan file.
    This captures ALL changes including nested ones.
    """
    changes = []
    
    # Plan files have a "resource_changes" key
    if "resource_changes" in plan:
        for resource_change in plan["resource_changes"]:
            address = resource_change.get("address", "unknown")
            change_type = resource_change.get("change", {})
            
            # Get before/after states
            before = change_type.get("before", {})
            after = change_type.get("after", {})
            
            # Determine action type
            if before is None and after is not None:
                action = "create"
            elif before is not None and after is None:
                action = "delete"
            elif before is not None and after is not None:
                # Check if there are actual changes
                if before == after:
                    action = "no-op"
                else:
                    action = "update"
            else:
                action = "no-op"
            
            # Use DeepDiff to find ALL nested changes
            detailed_changes = {}
            if before != after:
                diff = DeepDiff(before, after, ignore_order=False, verbose_level=2)
                detailed_changes = diff.to_dict()
            
            resource = ResourceChange(
                address=address,
                action=action,
                before=before if before else {},
                after=after if after else {},
                detailed_changes=detailed_changes
            )
            changes.append(resource)
    
    return changes

def filter_changes(changes: List[ResourceChange]) -> Tuple[List[ResourceChange], List[ResourceChange], List[ResourceChange], List[ResourceChange]]:
    """
    Categorize changes into: creates, updates, deletes, and no-ops.
    Returns: (creates, updates, deletes, no_ops)
    """
    creates = []
    updates = []
    deletes = []
    no_ops = []
    
    for change in changes:
        if change.action == "create":
            creates.append(change)
        elif change.action == "update":
            updates.append(change)
        elif change.action == "delete":
            deletes.append(change)
        else:
            no_ops.append(change)
    
    return creates, updates, deletes, no_ops

def format_nested_changes(detailed_changes: Dict[str, Any], indent: int = 4) -> str:
    """Format nested changes in a readable way."""
    lines = []
    indent_str = " " * indent
    
    for change_type, changes in detailed_changes.items():
        if isinstance(changes, dict):
            for key, value in changes.items():
                if isinstance(value, dict) and 'old_value' in value and 'new_value' in value:
                    old = value['old_value']
                    new = value['new_value']
                    lines.append(f"{indent_str}{change_type}: {key}")
                    lines.append(f"{indent_str}  Before: {old}")
                    lines.append(f"{indent_str}  After:  {new}")
                else:
                    lines.append(f"{indent_str}{change_type}: {key} = {value}")
    
    return "\n".join(lines)

def print_summary(creates: List[ResourceChange], updates: List[ResourceChange], 
                  deletes: List[ResourceChange], no_ops: List[ResourceChange]) -> None:
    """Print summary of all changes."""
    total_changes = len(creates) + len(updates) + len(deletes)
    
    print("\n" + "="*80)
    print("TERRAFORM PLAN ANALYSIS - STATE vs PLANNED CHANGES")
    print("="*80)
    
    print(f"\nSummary:")
    print(f"  ✓ Resources with NO changes:     {len(no_ops)}")
    print(f"  + Resources to CREATE:           {len(creates)}")
    print(f"  ~ Resources to MODIFY:           {len(updates)}")
    print(f"  - Resources to DELETE:           {len(deletes)}")
    print(f"  ─────────────────────────────")
    print(f"  Total planned changes:           {total_changes}")

def print_creates(creates: List[ResourceChange]) -> None:
    """Print resources that will be created."""
    if not creates:
        return
    
    print("\n" + "="*80)
    print(f"✓ RESOURCES TO CREATE ({len(creates)})")
    print("="*80)
    
    for resource in creates:
        print(f"\n+ {resource.address}")
        print(f"  Type: {resource.after.get('type', 'N/A')}")
        
        # Show key attributes being created
        if isinstance(resource.after, dict):
            for key in list(resource.after.keys())[:5]:  # Show first 5 keys
                value = resource.after[key]
                if isinstance(value, (str, int, bool)) and value:
                    print(f"    {key}: {value}")
        
        if resource.detailed_changes:
            print(f"  Changes detected:")
            print(format_nested_changes(resource.detailed_changes, 4))

def print_updates(updates: List[ResourceChange]) -> None:
    """Print resources that will be modified."""
    if not updates:
        return
    
    print("\n" + "="*80)
    print(f"~ RESOURCES TO MODIFY ({len(updates)})")
    print("="*80)
    
    for resource in updates:
        print(f"\n~ {resource.address}")
        
        if resource.detailed_changes:
            print(f"  Nested changes detected:")
            print(format_nested_changes(resource.detailed_changes, 4))
        else:
            print(f"  No detailed changes captured (may indicate list/set changes)")

def print_deletes(deletes: List[ResourceChange]) -> None:
    """Print resources that will be deleted."""
    if not deletes:
        return
    
    print("\n" + "="*80)
    print(f"✗ RESOURCES TO DELETE ({len(deletes)})")
    print("="*80)
    
    for resource in deletes:
        print(f"\n- {resource.address}")
        print(f"  Type: {resource.before.get('type', 'N/A')}")
        
        # Show key attributes being deleted
        if isinstance(resource.before, dict):
            for key in list(resource.before.keys())[:5]:  # Show first 5 keys
                value = resource.before[key]
                if isinstance(value, (str, int, bool)) and value:
                    print(f"    {key}: {value}")

def print_full_resource_json(resource: ResourceChange, action: str) -> None:
    """Print full JSON of a resource for detailed inspection."""
    print(f"\n  Full {action.upper()} configuration (JSON):")
    
    if action == "before":
        data = resource.before
    else:
        data = resource.after
    
    print(json.dumps(data, indent=4, default=str))

def main():
    if len(sys.argv) < 3:
        print("Usage: python drift-detector.py <state_file> <plan_file> [OPTIONS]")
        print("\nArguments:")
        print("  state_file     Path to applied terraform state file (.tfstate)")
        print("  plan_file      Path to planned changes file (.json from 'terraform show -json')")
        print("\nOptions:")
        print("  --verbose      Show full JSON of each resource change")
        print("  --creates      Only show resources to be created")
        print("  --updates      Only show resources to be modified")
        print("  --deletes      Only show resources to be deleted")
        print("\nExamples:")
        print("  python drift-detector.py terraform.tfstate plan.json")
        print("  python drift-detector.py terraform.tfstate plan.json --verbose")
        print("  python drift-detector.py terraform.tfstate plan.json --updates")
        print("\nHow to generate plan file:")
        print("  terraform plan -out=tfplan")
        print("  terraform show -json tfplan > plan.json")
        sys.exit(1)
    
    state_file = sys.argv[1]
    plan_file = sys.argv[2]
    verbose = "--verbose" in sys.argv
    filter_creates = "--creates" in sys.argv
    filter_updates = "--updates" in sys.argv
    filter_deletes = "--deletes" in sys.argv
    
    # Load files
    print(f"Loading state from: {state_file}")
    state = load_state_file(state_file)
    
    print(f"Loading plan from: {plan_file}")
    plan = load_plan_file(plan_file)
    
    # Extract and analyze changes
    print("\nAnalyzing planned changes...")
    changes = extract_plan_changes(plan)
    creates, updates, deletes, no_ops = filter_changes(changes)
    
    # Print summary
    print_summary(creates, updates, deletes, no_ops)
    
    # Print filtered results
    if not filter_creates and not filter_updates and not filter_deletes:
        # Show all if no filter
        print_creates(creates)
        print_updates(updates)
        print_deletes(deletes)
    else:
        # Show only what's requested
        if filter_creates:
            print_creates(creates)
        if filter_updates:
            print_updates(updates)
        if filter_deletes:
            print_deletes(deletes)
    
    # Verbose mode - show full JSON
    if verbose:
        print("\n" + "="*80)
        print("VERBOSE MODE - FULL RESOURCE CONFIGURATIONS")
        print("="*80)
        
        for create in creates:
            print(f"\n{create.address}:")
            print_full_resource_json(create, "after")
        
        for update in updates:
            print(f"\n{update.address}:")
            print_full_resource_json(update, "before")
            print(f"\n  ↓ BECOMES ↓\n")
            print_full_resource_json(update, "after")
        
        for delete in deletes:
            print(f"\n{delete.address}:")
            print_full_resource_json(delete, "before")

if __name__ == "__main__":
    main()