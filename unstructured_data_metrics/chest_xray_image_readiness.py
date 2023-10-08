import pydicom
import numpy as np
import matplotlib.pyplot as plt

def calculate_cnr_from_dicom(dicom_path):
    
    # Read DICOM file
    dicom_data = pydicom.dcmread(dicom_path)

    # Extract pixel array
    pixel_array = dicom_data.pixel_array

    # Calculate mean and standard deviation for the entire image
    image_mean, image_std = np.mean(pixel_array), np.std(pixel_array)

    # Optionally, display the histogram
    hist = plt.hist(pixel_array.flatten(), bins=256, range=[0,256], density=True)

    # Calculate CNR for the entire image
    cnr = (image_mean - 0) / image_std  # Assuming 0 as background intensity

    cnr_dict = {'Mean Intensity': image_mean, 'Standard Deviation (Quantum Noise)': image_std, 'CNR': cnr}
    return cnr_dict

def calculate_spatial_resolution(file_path):
    # Read the DICOM file
    dicom_dataset = pydicom.dcmread(file_path)

    # Extract pixel spacing
    pixel_spacing = dicom_dataset.get('PixelSpacing', None)

    if pixel_spacing is not None and len(pixel_spacing) == 2:
        # Calculate spatial resolution
        spatial_resolution_x = 1 / float(pixel_spacing[0])
        spatial_resolution_y = 1 / float(pixel_spacing[1])
        return {"Spatial Resolution X":spatial_resolution_x,"Spatial Resolution Y": spatial_resolution_y}
    else:
        return None


def detect_and_visualize_artifacts(dicom_file_path, threshold=0.95):
    # Load DICOM image
    dicom_data = pydicom.dcmread(dicom_file_path)
    image_array = dicom_data.pixel_array

    # Visualize the original image
    plt.figure(figsize=(8, 8))
    plt.imshow(image_array, cmap='gray')
    plt.title('Original DICOM Image')
    plt.axis('off')
    plt.show()

    # Detect and visualize artifacts based on user-defined threshold
    artifact_pixels = np.where(image_array >= np.max(image_array) * threshold)
    image_with_artifacts = np.copy(image_array)
    image_with_artifacts[artifact_pixels] = np.max(image_array)  # Set artifact pixels to the maximum

    # Visualize the image with artifacts
    plt.figure(figsize=(8, 8))
    plt.imshow(image_with_artifacts, cmap='gray')
    plt.title('DICOM Image with Artifacts Highlighted')
    plt.axis('off')
    plt.show()

    # Return the image array with artifacts for further analysis if needed
    return image_with_artifacts

def gather_image_quality_info(dicom_file_path):
    # Read the DICOM file
    dicom_data = pydicom.dcmread(dicom_file_path)

    # Initialize the dictionary to store image quality information
    image_quality_info = {}

    # Function to handle missing values
    def get_value(tag, default="N/A"):
        value = dicom_data.get(tag, default)
        return str(value).strip() if value is not None else default

    # Gather image quality information
    image_quality_info['Modality'] = get_value((0x0008, 0x0060))
    image_quality_info['Manufacturer'] = get_value((0x0008, 0x0070))

    image_quality_info['Row Dimension'] = get_value((0x0028, 0x0010))
    image_quality_info['Column Dimension'] = get_value((0x0028, 0x0011))
    image_quality_info['Bits Allocated'] = get_value((0x0028, 0x0100))
    image_quality_info['Bits Stored'] = get_value((0x0028, 0x0101))
    image_quality_info['Pixel Representation'] = get_value((0x0028, 0x0103))

    image_quality_info['Pixel Spacing'] = get_value((0x0028, 0x0030))

    image_quality_info['Window Center'] = get_value((0x0028, 0x1050))
    image_quality_info['Window Width'] = get_value((0x0028, 0x1051))
    image_quality_info['Rescale Intercept'] = get_value((0x0028, 0x1052))
    image_quality_info['Rescale Slope'] = get_value((0x0028, 0x1053))

    image_quality_info['Patient Position'] = get_value((0x0018, 0x5100))

    image_quality_info['Exposure Time'] = get_value((0x0018, 0x1150))
    image_quality_info['X-Ray Tube Current'] = get_value((0x0018, 0x1151))
    image_quality_info['Exposure In uAs'] = get_value((0x0018, 0x1152))

    image_quality_info['Contrast Bolus Agent'] = get_value((0x0018, 0x0010))
    image_quality_info['Contrast Bolus Start Time'] = get_value((0x0018, 0x1042))

    image_quality_info['Image Orientation Patient'] = get_value((0x0020, 0x0037))

    image_quality_info['Slice Thickness'] = get_value((0x0018, 0x0050))
    image_quality_info['Spacing Between Slices'] = get_value((0x0018, 0x0088))

    image_quality_info['Study Description'] = get_value((0x0008, 0x1030))
    image_quality_info['Study Date'] = get_value((0x0008, 0x0020))
    image_quality_info['Study Time'] = get_value((0x0008, 0x0030))

    return image_quality_info