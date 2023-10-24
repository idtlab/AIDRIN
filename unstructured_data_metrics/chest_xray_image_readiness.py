import io
import base64
import matplotlib.pyplot as plt
import numpy as np
import re
from io import BytesIO
import cv2

def calculate_cnr_from_dicom(dicom_data):
    
    # Read DICOM file

    # Extract pixel array
    pixel_array = dicom_data.pixel_array

    # Calculate mean and standard deviation for the entire image
    image_mean, image_std = np.mean(pixel_array), np.std(pixel_array)

    hist, bins, _ = plt.hist(pixel_array.flatten(), bins=256, range=[0, 256], density=False)
    
    # Create a figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 6))

    # Plot the intensity distribution
    ax1.bar(bins[:-1], hist, width=1, color='blue', alpha=0.7)
    ax1.set_title('Intensity Distribution')
    ax1.set_xlabel('Intensity')
    ax1.set_ylabel('Frequency')

    # Plot the original image
    ax2.imshow(pixel_array, cmap='gray')
    ax2.set_title('Original Image')
    ax2.axis('off')  # Turn off axis labels and ticks

    # Save the plot to a BytesIO object
    image_stream = io.BytesIO()
    plt.savefig(image_stream, format='png')
    plt.close(fig)

    # Move the "cursor" to the beginning of the BytesIO stream
    image_stream.seek(0)

    # Read the binary data from the stream
    binary_data = image_stream.read()

    # Encode the binary data to Base64
    base64_encoded = base64.b64encode(binary_data).decode('utf-8')

    # Calculate CNR for the entire image
    cnr = (image_mean - 0) / image_std  # Assuming 0 as background intensity

    cnr_dict = {
        'Mean Intensity': image_mean,
        'Standard Deviation (Quantum Noise)': image_std,
        'Contrast to Noise Ratio (CNR)': cnr,
        "Intensity Distribution Visualization": base64_encoded
    }
    return cnr_dict

def calculate_spatial_resolution(dicom_dataset):
    # Read the DICOM file
    # dicom_dataset = pydicom.dcmread(file_path,force=True)

    # Extract pixel spacing
    pixel_spacing = dicom_dataset.get('PixelSpacing', None)

    if pixel_spacing is not None and len(pixel_spacing) == 2:
        # Calculate spatial resolution
        spatial_resolution_x = 1 / float(pixel_spacing[0])
        spatial_resolution_y = 1 / float(pixel_spacing[1])
        return {"Spatial Resolution X":spatial_resolution_x,"Spatial Resolution Y": spatial_resolution_y}
    else:
        return {"Spatial Resolution X":"Unavailable","Spatial Resolution Y": "Unavailable"}


def detect_and_visualize_artifacts(dicom_data):
    # Load DICOM image
    # dicom_data = pydicom.dcmread(dicom_file_path, force=True)

    image_array = dicom_data.pixel_array

    # Apply GaussianBlur to reduce noise and improve thresholding
    blurred = cv2.GaussianBlur(image_array, (5, 5), 0)

    # Apply adaptive thresholding
    artifact_mask = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
    )

    # Create a plot
    plt.figure(figsize=(14, 8))

    # Plot the original image
    plt.subplot(1, 3, 1)
    plt.imshow(image_array, cmap='gray')
    plt.axis('off')
    plt.title('Original Image')

    # Plot the adaptive thresholded image
    plt.subplot(1, 3, 2)
    plt.imshow(artifact_mask, cmap='gray')
    plt.axis('off')
    plt.title('Artifact Mask')

    # Plot the image with artifacts
    image_with_artifacts = np.copy(image_array)
    image_with_artifacts[artifact_mask == 255] = np.max(image_array)  # Set artifact pixels to the maximum
    plt.subplot(1, 3, 3)
    plt.imshow(image_with_artifacts, cmap='gray')
    plt.axis('off')
    plt.title(f'Image with Artifacts usign adaptive thresholding')

    # Save the plot to a BytesIO object
    image_stream = io.BytesIO()
    plt.savefig(image_stream, format='png')
    plt.close()

    # Encode the BytesIO content as base64
    encoded_image = base64.b64encode(image_stream.getvalue()).decode('utf-8')

    return {
        "Image with Artifacts": encoded_image,
        "Description": "Identifies artifact pixels using adaptive thresholding.",
    }

    # # Return the base64-encoded images
    # original_image_base64 = plot_to_base64(image_array)
    # image_with_artifacts_base64 = plot_to_base64(image_with_artifacts)

    # return {"Image with Artifacts":image_with_artifacts_base64, "Description":"Identifies artifact pixels by locating those with intensity values surpassing a user-defined threshold, set as a percentage of the maximum intensity in the image","threshold":threshold}

def gather_image_quality_info(dicom_data):
    # Read the DICOM file
    # dicom_data = pydicom.dcmread(dicom_file_path)

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

    for key, value in image_quality_info.items():
        image_quality_info[key] = re.sub(r' {3,}', ' ', value)

    return image_quality_info