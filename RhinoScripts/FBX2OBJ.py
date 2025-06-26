import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino
import System
import os

def fbx_to_obj_converter():
    """
    Import FBX model, rotate 90 degrees counter-clockwise about Y axis, 
    and export as OBJ with same filename
    """
    
    # Get input FBX file
    fbx_filter = "FBX Files (*.fbx)|*.fbx||"
    fbx_file = rs.OpenFileName("Select FBX file to import", fbx_filter)
    
    if not fbx_file:
        print("No FBX file selected. Operation cancelled.")
        return
    
    # Get output folder
    output_folder = rs.BrowseForFolder("Select output folder for OBJ file")
    
    if not output_folder:
        print("No output folder selected. Operation cancelled.")
        return
    
    # Clear the document
    rs.Command("_SelAll")
    rs.Command("_Delete")
    
    # Import FBX file
    print("Importing FBX file: {}".format(fbx_file))
    import_command = '_-Import "{}" _Enter'.format(fbx_file)
    rs.Command(import_command)
    
    # Check if anything was imported
    all_objects = rs.AllObjects()
    if not all_objects:
        print("No objects were imported from the FBX file.")
        return
    
    print("Imported {} objects".format(len(all_objects)))
    
    # Select all imported objects
    rs.SelectObjects(all_objects)
    
    # Rotate 90 degrees counter-clockwise about X axis
    # Counter-clockwise rotation about X axis is negative rotation in Rhino
    center_point = [0, 0, 0]  # Origin
    axis_vector = [1, 0, 0]   # x axis
    angle = 90  # 90 degrees for counter-clockwise
    
    print("Rotating objects 90 degrees counter-clockwise about Y axis...")
    rs.RotateObjects(all_objects, center_point, angle, axis_vector)
    
    # Create output filename with same base name but .obj extension
    base_filename = os.path.splitext(os.path.basename(fbx_file))[0]
    obj_filename = base_filename + ".obj"
    obj_filepath = os.path.join(output_folder, obj_filename)
    
    # Export as OBJ
    print("Exporting as OBJ: {}".format(obj_filepath))
    
    # Select all objects for export
    rs.SelectObjects(all_objects)
    
    # Export command
    export_command = '_-Export "{}" _Enter'.format(obj_filepath)
    rs.Command(export_command)
    
    # Deselect all
    rs.UnselectAllObjects()
    
    print("Conversion completed successfully!")
    print("Input: {}".format(fbx_file))
    print("Output: {}".format(obj_filepath))

def fbx_to_obj_batch_converter():
    """
    Batch version that processes multiple FBX files from a folder
    """
    
    # Get input folder containing FBX files
    input_folder = rs.BrowseForFolder("Select folder containing FBX files")
    
    if not input_folder:
        print("No input folder selected. Operation cancelled.")
        return
    
    # Get output folder
    output_folder = rs.BrowseForFolder("Select output folder for OBJ files")
    
    if not output_folder:
        print("No output folder selected. Operation cancelled.")
        return
    
    # Find all FBX files in input folder
    fbx_files = []
    for file in os.listdir(input_folder):
        if file.lower().endswith('.fbx'):
            fbx_files.append(os.path.join(input_folder, file))
    
    if not fbx_files:
        print("No FBX files found in the selected folder.")
        return
    
    print("Found {} FBX files to process".format(len(fbx_files)))
    
    # Process each FBX file
    for i, fbx_file in enumerate(fbx_files):
        print("\nProcessing file {} of {}: {}".format(i + 1, len(fbx_files), os.path.basename(fbx_file)))
        
        # Clear the document
        rs.Command("_SelAll")
        rs.Command("_Delete")
        
        # Import FBX file
        import_command = '_-Import "{}" _Enter'.format(fbx_file)
        rs.Command(import_command)
        
        # Check if anything was imported
        all_objects = rs.AllObjects()
        if not all_objects:
            print("No objects were imported from {}".format(os.path.basename(fbx_file)))
            continue
        
        # Select all imported objects
        rs.SelectObjects(all_objects)
        
        # Rotate 90 degrees counter-clockwise about X axis
        center_point = [0, 0, 0]
        axis_vector = [1, 0, 0]
        angle = 90
        
        rs.RotateObjects(all_objects, center_point, angle, axis_vector)
        
        # Create output filename
        base_filename = os.path.splitext(os.path.basename(fbx_file))[0]
        obj_filename = base_filename + ".obj"
        obj_filepath = os.path.join(output_folder, obj_filename)
        
        # Export as OBJ
        rs.SelectObjects(all_objects)
        export_command = '_-Export "{}" _Enter'.format(obj_filepath)
        rs.Command(export_command)
        
        print("Exported: {}".format(obj_filename))
    
    rs.UnselectAllObjects()
    print("\nBatch conversion completed! Processed {} files.".format(len(fbx_files)))

# Main execution
if __name__ == "__main__":
    # Ask user which version to run
    choice = rs.GetString("Choose conversion type", "Single", ["Single", "Batch"])
    
    if choice == "Batch":
        fbx_to_obj_batch_converter()
    else:
        fbx_to_obj_converter()