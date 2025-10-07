#!/usr/bin/env python3
"""
Script to flip specified axes of vertices in an OBJ file by multiplying values by -1.
This effectively mirrors the model across the specified plane(s).
"""

import sys
import os
import argparse

def flip_obj_axes(input_file, output_file=None, flip_x=False, flip_y=False, flip_z=False, flip_normals=False):
    """
    Flip specified axes of all vertices and optionally normals in an OBJ file.
    
    Args:
        input_file (str): Path to the input OBJ file
        output_file (str, optional): Path to the output OBJ file. 
                                   If None, overwrites the input file.
        flip_x (bool): Whether to flip the X-axis
        flip_y (bool): Whether to flip the Y-axis
        flip_z (bool): Whether to flip the Z-axis
        flip_normals (bool): Whether to flip vertex normals accordingly
    """
    if output_file is None:
        output_file = input_file
    
    try:
        with open(input_file, 'r') as f:
            lines = f.readlines()
        
        modified_lines = []
        vertex_count = 0
        normal_count = 0
        axes_flipped = []
        
        # Track which axes are being flipped for reporting
        if flip_x:
            axes_flipped.append('X')
        if flip_y:
            axes_flipped.append('Y')
        if flip_z:
            axes_flipped.append('Z')
        
        for line in lines:
            # Check if line defines a vertex (starts with 'v ')
            if line.startswith('v '):
                parts = line.strip().split()
                if len(parts) >= 4:  # v x y z [w]
                    # Apply flips to specified axes
                    if flip_x:
                        parts[1] = str(float(parts[1]) * -1)  # Flip X
                    if flip_y:
                        parts[2] = str(float(parts[2]) * -1)  # Flip Y
                    if flip_z:
                        parts[3] = str(float(parts[3]) * -1)  # Flip Z
                    
                    modified_lines.append(' '.join(parts) + '\n')
                    vertex_count += 1
                else:
                    modified_lines.append(line)
            
            # Check if line defines a vertex normal (starts with 'vn ')
            elif line.startswith('vn ') and flip_normals:
                parts = line.strip().split()
                if len(parts) >= 4:  # vn nx ny nz
                    # Apply same flips to normals as vertices
                    if flip_x:
                        parts[1] = str(float(parts[1]) * -1)  # Flip normal X
                    if flip_y:
                        parts[2] = str(float(parts[2]) * -1)  # Flip normal Y
                    if flip_z:
                        parts[3] = str(float(parts[3]) * -1)  # Flip normal Z
                    
                    modified_lines.append(' '.join(parts) + '\n')
                    normal_count += 1
                else:
                    modified_lines.append(line)
            
            else:
                # Keep all other lines unchanged (faces, texture coords, etc.)
                modified_lines.append(line)
        
        # Write the modified content
        with open(output_file, 'w') as f:
            f.writelines(modified_lines)
        
        if axes_flipped:
            print(f"Successfully flipped {', '.join(axes_flipped)} ax{'is' if len(axes_flipped) == 1 else 'es'} for {vertex_count} vertices")
            if flip_normals and normal_count > 0:
                print(f"Also flipped {normal_count} vertex normals")
            elif flip_normals:
                print("Normal flipping requested but no vertex normals found in file")
        else:
            print(f"No axes specified for flipping. File copied unchanged.")
        print(f"Output saved to: {output_file}")
        
    except FileNotFoundError:
        print(f"Error: File '{input_file}' not found")
        return False
    except Exception as e:
        print(f"Error processing file: {e}")
        return False
    
    return True
