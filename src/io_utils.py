"""Input/output utilities for loading and writing clinical documents."""

import os
import json
from pathlib import Path
from typing import List, Dict
from src.models import ClinicalDocument, EntityOutput
from src.normalization import normalize_with_mapping


def validate_input_structure(input_dir: str) -> bool:
    """
    Validate that input directory exists and contains expected structure.
    
    Args:
        input_dir: Path to input directory
        
    Returns:
        True if valid, False otherwise
    """
    input_path = Path(input_dir)
    
    if not input_path.exists():
        print(f"Error: Input directory {input_dir} does not exist")
        return False
    
    if not input_path.is_dir():
        print(f"Error: {input_dir} is not a directory")
        return False
    
    # Check for .txt files
    txt_files = list(input_path.glob("*.txt"))
    if not txt_files:
        print(f"Warning: No .txt files found in {input_dir}")
        return False
    
    print(f"Found {len(txt_files)} .txt files in {input_dir}")
    return True


def load_single_file(filepath: str) -> ClinicalDocument:
    """
    Load a single clinical document from file.
    
    Args:
        filepath: Path to .txt file
        
    Returns:
        ClinicalDocument object
    """
    path = Path(filepath)
    
    # Extract file_id from filename (e.g., "1.txt" -> "1")
    file_id = path.stem
    
    # Read raw text with UTF-8 encoding
    with open(filepath, 'r', encoding='utf-8') as f:
        raw_text = f.read()
    
    normalized_text, norm_to_raw_map, raw_to_norm_map = normalize_with_mapping(raw_text, for_matching=True)

    doc = ClinicalDocument(
        file_id=file_id,
        raw_text=raw_text,
        normalized_text=normalized_text,
        norm_to_raw_map=norm_to_raw_map,
        raw_to_norm_map=raw_to_norm_map,
    )
    
    return doc


def load_input_files(input_dir: str) -> List[ClinicalDocument]:
    """
    Load all clinical documents from input directory.
    
    Args:
        input_dir: Path to directory containing .txt files
        
    Returns:
        List of ClinicalDocument objects, sorted by numeric file_id
    """
    if not validate_input_structure(input_dir):
        return []
    
    input_path = Path(input_dir)
    documents = []
    
    # Load all .txt files
    for txt_file in input_path.glob("*.txt"):
        try:
            doc = load_single_file(str(txt_file))
            documents.append(doc)
        except Exception as e:
            print(f"Error loading {txt_file}: {e}")
            continue
    
    # Sort by numeric file_id
    documents.sort(key=lambda d: int(d.file_id))
    
    print(f"Successfully loaded {len(documents)} documents")
    return documents


def write_output_json(entities: List[EntityOutput], output_path: str) -> bool:
    """
    Write entities to JSON file in submission format.
    
    Args:
        entities: List of EntityOutput objects
        output_path: Path to output .json file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Convert entities to dictionaries
        output_data = [entity.to_dict() for entity in entities]
        
        # Ensure output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Write JSON with Vietnamese character support
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        print(f"Error writing output to {output_path}: {e}")
        return False


def create_output_zip(output_dir: str, zip_path: str) -> bool:
    """
    Create output.zip from output directory.
    
    Args:
        output_dir: Directory containing output JSON files
        zip_path: Path for output zip file
        
    Returns:
        True if successful, False otherwise
    """
    import zipfile
    
    try:
        output_path = Path(output_dir)
        if not output_path.exists():
            print(f"Error: Output directory {output_dir} does not exist")
            return False
        
        # Create zip file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add all JSON files
            for json_file in output_path.glob("*.json"):
                # Add with relative path inside 'output' folder
                arcname = f"output/{json_file.name}"
                zipf.write(json_file, arcname)
        
        print(f"Created {zip_path}")
        return True
    except Exception as e:
        print(f"Error creating zip file: {e}")
        return False
