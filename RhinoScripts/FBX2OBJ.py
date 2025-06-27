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
    
    # Rotate 90 degrees counter-clockwise about Y axis
    # Counter-clockwise rotation about Y axis is negative rotation in Rhino
    center_point = [0, 0, 0]  # Origin
    axis_vector = [1, 0, 0]   # Y axis
    angle = 90  # -90 degrees for counter-clockwise
    
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
    Batch version that searches for LOD400 folders and processes FBX files within them
    Creates subfolders in output directory matching model names
    """
    
    # Get input folder to search for LOD400 directories
    input_folder = rs.BrowseForFolder("Select root folder to search for LOD400 directories")
    
    if not input_folder:
        print("No input folder selected. Operation cancelled.")
        return
    
    # Get output folder
    output_folder = rs.BrowseForFolder("Select output folder for OBJ files")
    
    if not output_folder:
        print("No output folder selected. Operation cancelled.")
        return
    
    # Find all LOD400 folders recursively
    lod400_folders = []
    print("Searching for LOD400 folders...")
    
    for root, dirs, files in os.walk(input_folder):
        for dir_name in dirs:
            if dir_name == "LOD400":
                lod400_path = os.path.join(root, dir_name)
                lod400_folders.append(lod400_path)
                print("Found LOD400 folder: {}".format(lod400_path))
    
    if not lod400_folders:
        print("No LOD400 folders found in the directory tree.")
        return
    
    print("Found {} LOD400 folders to process".format(len(lod400_folders)))
    
    total_processed = 0
    
    # Process each LOD400 folder
    for lod_folder in lod400_folders:
        print("\nProcessing LOD400 folder: {}".format(lod_folder))
        
        # Find FBX files in this LOD400 folder
        fbx_files = []
        for file in os.listdir(lod_folder):
            if file.lower().endswith('.fbx'):
                fbx_files.append(os.path.join(lod_folder, file))
        
        if not fbx_files:
            print("No FBX files found in {}".format(lod_folder))
            continue
        
        print("Found {} FBX files in this folder".format(len(fbx_files)))
        
        # Process each FBX file in this LOD400 folder
        for fbx_file in fbx_files:
            print("Processing: {}".format(os.path.basename(fbx_file)))
            
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
            
            # Rotate 90 degrees counter-clockwise about Y axis
            center_point = [0, 0, 0]
            axis_vector = [1, 0, 0]
            angle = 90
            
            rs.RotateObjects(all_objects, center_point, angle, axis_vector)
            
            # Create output subfolder with model name (without extension)
            base_filename = os.path.splitext(os.path.basename(fbx_file))[0]
            model_output_folder = os.path.join(output_folder, base_filename)
            
            # Create the subfolder if it doesn't exist
            if not os.path.exists(model_output_folder):
                os.makedirs(model_output_folder)
                print("Created output folder: {}".format(model_output_folder))
            
            # Create full output path
            obj_filename = base_filename + ".obj"
            obj_filepath = os.path.join(model_output_folder, obj_filename)
            
            # Export as OBJ
            rs.SelectObjects(all_objects)
            export_command = '_-Export "{}" _Enter'.format(obj_filepath)
            rs.Command(export_command)
            
            print("Exported: {}".format(obj_filepath))
            total_processed += 1
    
    rs.UnselectAllObjects()
    print("\nBatch conversion completed!")
    print("Total LOD400 folders found: {}".format(len(lod400_folders)))
    print("Total FBX files processed: {}".format(total_processed))

# Main execution
if __name__ == "__main__":
    # Ask user which version to run
    choice = rs.GetString("Choose conversion type", "Single", ["Single", "Batch"])
    
    if choice == "Batch":
        fbx_to_obj_batch_converter()
    else:
        fbx_to_obj_converter()