function togglePillarDropdown(id) {
  const container = document.getElementById(id); //
  const subElements = container.querySelectorAll(".toggle-button");

  const header = document.querySelector(`h3[onclick*="${id}"]`);
  const svg = header.querySelector("svg");
  subElements.forEach((element) => {
    if (element.style.display === "none" || element.style.display === "") {
      element.style.display = "flex";
      svg.innerHTML = '<path d="M480-360 280-559.33h400L480-360Z"/>';
    } else {
      element.style.display = "none";
      svg.innerHTML = '<path d="M400-280v-400l200 200-200 200Z"/>';
    }
  });
}

//for uploads
function uploadForm() {
  const form = document.getElementById("uploadForm");
  const fileTypeSelector = document.getElementById("fileTypeSelector");
  const fileInput = document.getElementById("file");
  
  // Check if file type is selected
  if (!fileTypeSelector.value) {
    alert("Please select a file type first");
    return;
  }
  
  // Check if file is selected
  if (!fileInput.files || fileInput.files.length === 0) {
    alert("Please select a file to upload");
    return;
  }
  
  // Submit the form normally
  form.submit();
}

//to clear
function clearFile() {
  fetch("/clear", {
    method: "POST",
  })
    .then((response) => {
      if (response.redirected) {
        // Redirect to the specified location
        window.location.href = response.url;
      }
    })
    .catch((error) => {
      console.error("Error:", error);
      openErrorPopup("File Clear", error); // call error popup
    });
}

//changes file upload ability
function updateFileInputBasedOnType(
  fileTypeElement,
  fileInput,
  fileUploadMessage
) {
  const fileType = fileTypeElement.value;
  //if a filetype is present, set to that filetype only, otherwise disable
  if (fileType) {
    fileInput.disabled = false;
    fileInput.setAttribute("accept", fileType);
    console.log("USER SELECTED FILETYPE: " + fileType);
    fileUploadMessage.style.opacity = "1";
    fileUploadMessage.style.fontSize = "1.5em";
    fileTypeSelector.style.fontSize = "1.25em";
  } else {
    fileInput.disabled = true;
    fileInput.removeAttribute("accept");
    fileUploadMessage.style.opacity = "0";
    fileUploadMessage.style.fontSize = "0px";
    fileTypeSelector.style.fontSize = "1.75em";
    console.log("FILE UPLOAD DISABLED");
  }
}

// Add these functions before the submitForm function



// Function to categorize error types for DP Statistics
function getDPStatisticsErrorType(errorMessage) {
    if (errorMessage.includes("No numerical features selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("Invalid numerical features selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("Invalid epsilon value")) {
        return "Parameter Error";
    } else if (errorMessage.includes("Invalid epsilon value format")) {
        return "Parameter Error";
    } else if (errorMessage.includes("Dataset is empty")) {
        return "Data Error";
    } else if (errorMessage.includes("Processing error")) {
        return "Processing Error";
    } else {
        return "Error";
    }
}



// Function to categorize error types for Single Attribute Risk Scoring
function getSingleAttributeRiskErrorType(errorMessage) {
    if (errorMessage.includes("No quasi-identifiers selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("No valid quasi-identifiers provided")) {
        return "Selection Error";
    } else if (errorMessage.includes("not found in dataset")) {
        return "Data Error";
    } else if (errorMessage.includes("must contain unique values")) {
        return "Data Error";
    } else if (errorMessage.includes("appear to be numerical")) {
        return "Data Error";
    } else if (errorMessage.includes("no data remains")) {
        return "Data Error";
    } else if (errorMessage.includes("has only one unique value")) {
        return "Data Error";
    } else if (errorMessage.includes("already a perfect identifier")) {
        return "Data Error";
    } else if (errorMessage.includes("causing division by zero")) {
        return "Processing Error";
    } else if (errorMessage.includes("task timed out")) {
        return "Timeout Error";
    } else if (errorMessage.includes("Processing error")) {
        return "Processing Error";
    } else {
        return "Error";
    }
}



// Function to categorize error types for Multiple Attribute Risk Scoring
function getMultipleAttributeRiskErrorType(errorMessage) {
    if (errorMessage.includes("No quasi-identifiers selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("No ID feature selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("Input DataFrame is empty")) {
        return "Data Error";
    } else if (errorMessage.includes("must be a string or list")) {
        return "Parameter Error";
    } else if (errorMessage.includes("No valid columns provided")) {
        return "Selection Error";
    } else if (errorMessage.includes("Columns not found in dataset")) {
        return "Data Error";
    } else if (errorMessage.includes("not found in dataset")) {
        return "Data Error";
    } else if (errorMessage.includes("must contain unique values")) {
        return "Data Error";
    } else if (errorMessage.includes("has only one unique value")) {
        return "Data Error";
    } else if (errorMessage.includes("is a perfect identifier")) {
        return "Data Error";
    } else if (errorMessage.includes("After dropping missing values")) {
        return "Data Error";
    } else if (errorMessage.includes("causing division by zero")) {
        return "Processing Error";
    } else if (errorMessage.includes("Multiple Attribute Risk task timed out")) {
        return "Timeout Error";
    } else if (errorMessage.includes("Processing error")) {
        return "Processing Error";
    } else {
        return "Error";
    }
}



// Function to categorize error types for Entropy Risk
function getEntropyRiskErrorType(errorMessage) {
    if (errorMessage.includes("No quasi-identifiers selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("Input DataFrame is empty")) {
        return "Data Error";
    } else if (errorMessage.includes("not found in the dataset")) {
        return "Data Error";
    } else if (errorMessage.includes("No data left after dropping rows")) {
        return "Data Error";
    } else if (errorMessage.includes("Entropy Risk task timed out")) {
        return "Timeout Error";
    } else if (errorMessage.includes("Processing error")) {
        return "Processing Error";
    } else {
        return "Error";
    }
}

// Function to categorize error types for k-Anonymity
function getKAnonymityErrorType(errorMessage) {
    if (errorMessage.includes("No quasi-identifiers selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("Input DataFrame is empty")) {
        return "Data Error";
    } else if (errorMessage.includes("not found in the dataset")) {
        return "Data Error";
    } else if (errorMessage.includes("No data left after dropping rows")) {
        return "Data Error";
    } else if (errorMessage.includes("K-Anonymity task timed out")) {
        return "Timeout Error";
    } else if (errorMessage.includes("Processing error")) {
        return "Processing Error";
    } else {
        return "Error";
    }
}

// Function to categorize error types for L-Diversity
function getLDiversityErrorType(errorMessage) {
    if (errorMessage.includes("No quasi-identifiers selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("No sensitive attribute selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("Input DataFrame is empty")) {
        return "Data Error";
    } else if (errorMessage.includes("not found in the dataset")) {
        return "Data Error";
    } else if (errorMessage.includes("No data left after dropping rows")) {
        return "Data Error";
    } else if (errorMessage.includes("L-Diversity task timed out")) {
        return "Timeout Error";
    } else if (errorMessage.includes("Processing error")) {
        return "Processing Error";
    } else {
        return "Error";
    }
}

// Function to categorize error types for T-Closeness
function getTClosenessErrorType(errorMessage) {
    if (errorMessage.includes("No quasi-identifiers selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("No sensitive attribute selected")) {
        return "Selection Error";
    } else if (errorMessage.includes("Input DataFrame is empty")) {
        return "Data Error";
    } else if (errorMessage.includes("not found in the dataset")) {
        return "Data Error";
    } else if (errorMessage.includes("No data left after dropping rows")) {
        return "Data Error";
    } else if (errorMessage.includes("T-Closeness task timed out")) {
        return "Timeout Error";
    } else if (errorMessage.includes("Processing error")) {
        return "Processing Error";
    } else {
        return "Error";
    }
}







function submitForm() {
  var form = document.getElementById("uploadForm");
  var formData = new FormData(form);

  // Get the values of the checkboxes and concatenate them with a comma
  var checkboxValues = Array.from(formData.getAll("checkboxValues")).join(",");
  var numFeaCheckboxValues = Array.from(
    formData.getAll("numerical features for feature relevancy")
  ).join(",");
  var catFeaCheckboxValues = Array.from(
    formData.getAll("categorical features for feature relevancy")
  ).join(",");

  // Add the concatenated checkbox values to the form data
  formData.set("correlation columns", checkboxValues);
  formData.set(
    "numerical features for feature relevancy",
    numFeaCheckboxValues
  );
  formData.set(
    "categorical features for feature relevancy",
    catFeaCheckboxValues
  );

  // Note: We don't need to modify the quasi-identifier fields as they should remain as lists
  // The backend will handle both string and list formats
  // Populate metrics visualizations
  var metrics = document.getElementById("metrics");
  if (metrics) {
    metrics.innerHTML = "<p>Loading visualizations, please wait...</p>";
  } else {
    console.error("No Element ID");
    console.log("No Element ID");
    print("No Element ID");
  }
  const url = new URL(window.location.href);
  url.searchParams.set("returnType", "json");
  const currentURL = url.toString();
  fetch(currentURL, {
    method: "POST",
    body: formData,
  })
    .then((response) => {
      if (
        response.ok &&
        response.headers.get("content-type")?.includes("application/json")
      ) {
        return response.json();
      } else {
        throw new Error("Server did not return valid JSON.");
      }
    })
    .then((data) => {
      if (data.trigger === "correlationError") {
        openErrorPopup(
          "Invalid Request",
          "Input Feature and Target Feature cannot be the same"
        ); // call error popup
      }
      if (data.error) {
        openErrorPopup("", data.error); // call error popup
      }
      console.log("Server Response:", data);
      var resultContainer = document.getElementById("resultContainer");
      resp_data = data;

      // Function to check if a key is present and not undefined
      function isKeyPresentAndDefined(obj, key) {
        return obj && obj[key] !== undefined;
      }

      var visualizationContent = [];

      // Check for each type of visualization
      var visualizationTypes = [
            'Completeness', 'Outliers', 'Representation Rate', 'Statistical Rate', 
            'Correlations Analysis Categorical', 'Correlations Analysis Numerical',
            'Feature Relevance', 'Class Imbalance', 'DP Statistics', 
            'Single attribute risk scoring', 'Multiple attribute risk scoring',
            'k-Anonymity', 'l-Diversity', 't-Closeness', 'Entropy Risk'
        ];
        
        // First, check for validation errors and show popups immediately
        visualizationTypes.forEach(function(type) {
            if (isKeyPresentAndDefined(data, type) && data[type]['Error']) {
                console.log('Validation/Processing error in', type, ':', data[type]['Error']);
                
                // Show error popup immediately for all error types
                if (type === 'DP Statistics') {
                    const errorType = getDPStatisticsErrorType(data[type]['Error']);
                    openErrorPopup(
                        errorType,
                        data[type]['Error'] 
                    );
                } else if (type === 'Single attribute risk scoring') {
                    const errorType = getSingleAttributeRiskErrorType(data[type]['Error']);
                    openErrorPopup(
                        errorType,
                        data[type]['Error'] 
                    );
                } else if (type === 'Multiple attribute risk scoring') {
                    const errorType = getMultipleAttributeRiskErrorType(data[type]['Error']);
                    openErrorPopup(
                        errorType,
                        data[type]['Error'] 
                    );
                } else if (type === 'Entropy Risk') {
                    const errorType = getEntropyRiskErrorType(data[type]['Error']);
                    openErrorPopup(
                        errorType,
                        data[type]['Error'] 
                    );
                } else if (type === 'k-Anonymity') {
                    const errorType = getKAnonymityErrorType(data[type]['Error']);
                    openErrorPopup(
                        errorType,
                        data[type]['Error'] 
                    );
                } else if (type === 'l-Diversity') {
                    const errorType = getLDiversityErrorType(data[type]['Error']);
                    openErrorPopup(
                        errorType,
                        data[type]['Error'] 
                    );
                } else if (type === 't-Closeness') {
                    const errorType = getTClosenessErrorType(data[type]['Error']);
                    openErrorPopup(
                        errorType,
                        data[type]['Error'] 
                    );
                } else {
                    // For other metrics, show generic error popup
                    openErrorPopup(
                        'Error',
                        data[type]['Error'] 
                    );
                }
            }
        });
        
        // Debug: Log the entire data structure to see what we're receiving
        console.log('DEBUG: Full data structure received:', data);
        console.log('DEBUG: Checking for Single attribute risk scoring errors...');
        if (data['Single attribute risk scoring']) {
            console.log('DEBUG: Single attribute risk scoring data:', data['Single attribute risk scoring']);
            if (data['Single attribute risk scoring']['Error']) {
                console.log('DEBUG: Found error in Single attribute risk scoring:', data['Single attribute risk scoring']['Error']);
            } else {
                console.log('DEBUG: No error found in Single attribute risk scoring');
            }
        } else {
            console.log('DEBUG: Single attribute risk scoring not found in data');
        }
        
        visualizationTypes.forEach(function(type) {
            console.log('Checking type:', type);
            if (isKeyPresentAndDefined(data, type)) {
                console.log('Found type in data:', type);
                
                // Check if this is an async task (for MM risk scoring)
                if (data[type]['is_async']) {
                    console.log('Adding async task placeholder:', type);
                    var title = type;
                    var jsonData = JSON.stringify(data);
                    
                    // Create placeholder for async task
                    visualizationContent.push({
                        image: "",
                        riskScore: 'N/A',
                        riskLevel: null,
                        riskColor: null,
                        value: 'N/A',
                        description: '',
                        interpretation: '',
                        title: title,
                        jsonData: jsonData,
                        hasError: false,
                        isAsync: true,
                        taskId: data[type]['task_id'],
                        cacheKey: data[type]['cache_key']
                    });
                    
                    // Start polling for this task
                    console.log('Starting polling for task:', data[type]['task_id'], 'for metric:', type);
                    console.log('Task details:', {
                        taskId: data[type]['task_id'],
                        cacheKey: data[type]['cache_key'],
                        metricName: type,
                        status: data[type]['status']
                    });
                    pollAsyncTask(data[type]['task_id'], data[type]['cache_key'], type);
                    
                } else if (isKeyPresentAndDefined(data[type], type + ' Visualization')) {
                    console.log('Adding visualization:', type);
                    var image = data[type][type + ' Visualization'];
                    // Ensure image is a string
                    if (typeof image !== 'string') {
                        image = image ? String(image) : "";
                    }
                    // Handle specific field names for privacy metrics and class imbalance
                    var value = 'N/A';
                    if (type === 'k-Anonymity' && data[type]['k-Value'] !== undefined) {
                        value = data[type]['k-Value'];
                    } else if (type === 'l-Diversity' && data[type]['l-Value'] !== undefined) {
                        value = data[type]['l-Value'];
                    } else if (type === 't-Closeness' && data[type]['t-Value'] !== undefined) {
                        value = data[type]['t-Value'];
                    } else if (type === 'Entropy Risk' && data[type]['Entropy-Value'] !== undefined) {
                        value = data[type]['Entropy-Value'];
                    } else if (type === 'Class Imbalance' && data[type]['Imbalance degree'] && data[type]['Imbalance degree']['Imbalance Degree score'] !== undefined) {
                        value = data[type]['Imbalance degree']['Imbalance Degree score'];
                    } else if (data[type]['Value'] !== undefined) {
                        value = data[type]['Value'];
                    } 
                    // Handle specific field names for privacy metrics descriptions and class imbalance
                    var description = '';
                    var interpretation = '';
                    
                    if (type === 'k-Anonymity' || type === 'l-Diversity' || type === 't-Closeness' || type === 'Entropy Risk') {
                        description = data[type]['Description'] || '';
                        interpretation = data[type]['Graph interpretation'] || '';
                    } else if (type === 'Class Imbalance') {
                        // Class Imbalance has nested structure for description
                        description = data[type]['Description'] || '';
                        if (data[type]['Imbalance degree'] && data[type]['Imbalance degree']['Description']) {
                            interpretation = data[type]['Imbalance degree']['Description'] || '';
                        } else {
                            interpretation = '';
                        }
                    } else {
                        description = data[type]['Description'] || '';
                        interpretation = data[type]['Graph interpretation'] || '';
                    }
                    var riskScore = data[type]['Risk Score'] || 'N/A'; 
                    var riskLevel = data[type]['Risk Level'] || null;
                    var riskColor = data[type]['Risk Color'] || null;
                    var title = type;
                    var jsonData = JSON.stringify(data);
                    
                    // Check if there's an error or if the image is empty
                    if (data[type]['Error']) {
                        console.log('Error in', type, ':', data[type]['Error']);
                        
                        // Special handling for DP Statistics errors
                        if (type === 'DP Statistics') {
                            // Enhanced error handling for DP Statistics - show as popup
                            const errorType = getDPStatisticsErrorType(data[type]['Error']);
                            
                            // Show error popup immediately
                            openErrorPopup(
                                errorType,
                                data[type]['Error'] 
                            );
                            
                            // Add to visualization content with minimal error display
                            visualizationContent.push({
                                image: "",
                                riskScore: 'N/A',
                                riskLevel: null,
                                riskColor: null,
                                value: 'N/A',
                                description: '',
                                interpretation: '',
                                title: title,
                                jsonData: jsonData,
                                hasError: true,
                                isDPStatistics: true,
                                errorDetails: {
                                    errorMessage: data[type]['Error'],
                                    errorType: errorType
                                }
                            });
                        } else if (type === 'Single attribute risk scoring') {
                            // Enhanced error handling for Single Attribute Risk Scoring - show as popup
                            const errorType = getSingleAttributeRiskErrorType(data[type]['Error']);
                            
                            // Show error popup immediately
                            openErrorPopup(
                                errorType,
                                data[type]['Error'] 
                            );
                            
                            // Add to visualization content with minimal error display
                            visualizationContent.push({
                                image: "",
                                riskScore: 'N/A',
                                riskLevel: null,
                                riskColor: null,
                                value: 'N/A',
                                description: '',
                                interpretation: '',
                                title: title,
                                jsonData: jsonData,
                                hasError: true,
                                isSingleAttributeRisk: true,
                                errorDetails: {
                                    errorMessage: data[type]['Error'],
                                    errorType: errorType
                                }
                            });
                        } else if (type === 'Multiple attribute risk scoring') {
                            // Enhanced error handling for Multiple Attribute Risk Scoring - show as popup
                            const errorType = getMultipleAttributeRiskErrorType(data[type]['Error']);
                            
                            // Show error popup immediately
                            openErrorPopup(
                                errorType,
                                data[type]['Error'] 
                            );
                            
                            // Add to visualization content with minimal error display
                            visualizationContent.push({
                                image: "",
                                riskScore: 'N/A',
                                riskLevel: null,
                                riskColor: null,
                                value: 'N/A',
                                description: '',
                                interpretation: '',
                                title: title,
                                jsonData: jsonData,
                                hasError: true,
                                isMultipleAttributeRisk: true,
                                errorDetails: {
                                    errorMessage: data[type]['Error'],
                                    errorType: errorType
                                }
                            });
                        } else if (type === 'Entropy Risk') {
                            // Enhanced error handling for Entropy Risk - show as popup
                            const errorType = getEntropyRiskErrorType(data[type]['Error']);
                            
                            // Show error popup immediately
                            openErrorPopup(
                                errorType,
                                data[type]['Error'] 
                            );
                            
                            // Add to visualization content with minimal error display
                            visualizationContent.push({
                                image: "",
                                riskScore: 'N/A',
                                riskLevel: null,
                                riskColor: null,
                                value: 'N/A',
                                description: '',
                                interpretation: '',
                                title: title,
                                jsonData: jsonData,
                                hasError: true,
                                isEntropyRisk: true,
                                errorDetails: {
                                    errorMessage: data[type]['Error'],
                                    errorType: errorType
                                }
                            });
                        } else if (type === 'k-Anonymity') {
                            // Enhanced error handling for k-Anonymity - show as popup
                            const errorType = getKAnonymityErrorType(data[type]['Error']);
                            
                            // Show error popup immediately
                            openErrorPopup(
                                errorType,
                                data[type]['Error'] 
                            );
                            
                            // Add to visualization content with minimal error display
                            visualizationContent.push({
                                image: "",
                                riskScore: 'N/A',
                                riskLevel: null,
                                riskColor: null,
                                value: 'N/A',
                                description: '',
                                interpretation: '',
                                title: title,
                                jsonData: jsonData,
                                hasError: true,
                                isKAnonymity: true,
                                errorDetails: {
                                    errorMessage: data[type]['Error'],
                                    errorType: errorType
                                }
                            });
                        } else if (type === 'l-Diversity') {
                            // Enhanced error handling for l-Diversity - show as popup
                            const errorType = getLDiversityErrorType(data[type]['Error']);
                            
                            // Show error popup immediately
                            openErrorPopup(
                                errorType,
                                data[type]['Error'] 
                            );
                            
                            // Add to visualization content with minimal error display
                            visualizationContent.push({
                                image: "",
                                riskScore: 'N/A',
                                riskLevel: null,
                                riskColor: null,
                                value: 'N/A',
                                description: '',
                                interpretation: '',
                                title: title,
                                jsonData: jsonData,
                                hasError: true,
                                isLDiversity: true,
                                errorDetails: {
                                    errorMessage: data[type]['Error'],
                                    errorType: errorType
                                }
                            });
                        } else if (type === 't-Closeness') {
                            // Enhanced error handling for t-Closeness - show as popup
                            const errorType = getTClosenessErrorType(data[type]['Error']);
                            
                            // Show error popup immediately
                            openErrorPopup(
                                errorType,
                                data[type]['Error'] 
                            );
                            
                            // Add to visualization content with minimal error display
                            visualizationContent.push({
                                image: "",
                                riskScore: 'N/A',
                                riskLevel: null,
                                riskColor: null,
                                value: 'N/A',
                                description: '',
                                interpretation: '',
                                title: title,
                                jsonData: jsonData,
                                hasError: true,
                                isTCloseness: true,
                                errorDetails: {
                                    errorMessage: data[type]['Error'],
                                    errorType: errorType
                                }
                            });
                        } else {
                            // Standard error handling for other metrics
                            visualizationContent.push({
                                image: image || "",
                                riskScore: riskScore,
                                riskLevel: riskLevel,
                                riskColor: riskColor,
                                value: value,
                                description: description,
                                interpretation: interpretation,
                                title: title,
                                jsonData: jsonData,
                                hasError: true,
                                isDPStatistics: false
                            });
                        }
                    } else if (image && image.trim() !== "") {
                        visualizationContent.push({
                            image: image,
                            riskScore: riskScore,
                            riskLevel: riskLevel,
                            riskColor: riskColor,
                            value: value,
                            description: description,
                            interpretation: interpretation,
                            title: title,
                            jsonData: jsonData,
                            hasError: false
                        });
                    } else {
                        console.log('Empty visualization for:', type);
                    }
                } else {
                    console.log('Missing visualization key for:', type, 'Expected:', type + ' Visualization');
                }
            } else {
                console.log('Type not found in data:', type);
        }
      });
      // Boolean flag to track if heading has been added
      var headingAdded = false;

      if (visualizationContent.length > 0) {
        // Add heading if not already added
        if (!headingAdded) {
          metrics.innerHTML = `<div class="heading">Readiness Report</div>`;

          headingAdded = true;
        }
        console.log("Visualization content:", visualizationContent);
        // Add each visualization to the metric visualization section
        visualizationContent.forEach(function (content, index) {
          const imageBlobUrl = `data:image/jpeg;base64,${content.image}`;
          const visualizationId = `visualization_${index}`;
          let visualizationHtml = `<div class="visualization-container">
                    <div class="toggle" style="display:block" onclick="toggleVisualization('${visualizationId}')">
                        <div style="display: flex; justify-content:space-between; align-items: center;">
                            <div>${content.title}</div>
                            <svg id="${visualizationId}-toggle-arrow" xmlns="http://www.w3.org/2000/svg" height="35px" viewBox="0 -960 960 960" width="36px" fill="currentColor"><path d="M480-360 280-560h400L480-360Z"/></svg>
                        </div>
                    </div>
                        <div id="${visualizationId}" style="display: none;">`;

          if (content.hasError) {
            if (content.isDPStatistics) {
                // Simple error display for DP Statistics (detailed info shown in popup)
                visualizationHtml += `
                    <div class="error-container" style="text-align: center; padding: 20px; border: 2px solid #d32f2f; border-radius: 8px; background-color: #ffebee; margin-bottom: 20px;">
                        <div style="color: #d32f2f; margin-bottom: 15px;">
                            <svg xmlns="http://www.w3.org/2000/svg" height="32px" viewBox="0 -960 960 960" width="32px" fill="#d32f2f" style="margin-bottom: 10px;">
                                <path d="M480-280q17 0 28.5-11.5T520-320q0-17-11.5-28.5T480-360q-17 0-28.5 11.5T440-320q0 17 11.5 28.5T480-280Zm-40-160h80v-240h-80v240Zm40 360q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-197q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Z"/>
                            </svg>
                            <h4 style="margin: 0; color: #d32f2f;">Error in DP Statistics</h4>
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <p style="margin: 10px 0; font-size: 14px; color: #333;">
                                An error occurred while processing differential privacy statistics.
                            </p>
                            <p style="margin: 10px 0; font-size: 14px; color: #666;">
                                <strong>Error:</strong> ${content.errorDetails.errorMessage}
                            </p>
                        </div>
                    </div>
                `;
            } else if (content.isSingleAttributeRisk) {
                // Simple error display for Single Attribute Risk Scoring (detailed info shown in popup)
                visualizationHtml += `
                    <div class="error-container" style="text-align: center; padding: 20px; border: 2px solid #d32f2f; border-radius: 8px; background-color: #ffebee; margin-bottom: 20px;">
                        <div style="color: #d32f2f; margin-bottom: 15px;">
                            <svg xmlns="http://www.w3.org/2000/svg" height="32px" viewBox="0 -960 960 960" width="32px" fill="#d32f2f" style="margin-bottom: 10px;">
                                <path d="M480-280q17 0 28.5-11.5T520-320q0-17-11.5-28.5T480-360q-17 0-28.5 11.5T440-320q0 17 11.5 28.5T480-280Zm-40-160h80v-240h-80v240Zm40 360q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-197q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Z"/>
                            </svg>
                            <h4 style="margin: 0; color: #d32f2f;">Error in Single Attribute Risk Scoring</h4>
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <p style="margin: 10px 0; font-size: 14px; color: #333;">
                                An error occurred while processing single attribute risk scores.
                            </p>
                            <p style="margin: 10px 0; font-size: 14px; color: #666;">
                                <strong>Error:</strong> ${content.errorDetails.errorMessage}
                            </p>
                        </div>
                    </div>
                `;
            } else if (content.isMultipleAttributeRisk) {
                // Simple error display for Multiple Attribute Risk Scoring (detailed info shown in popup)
                visualizationHtml += `
                    <div class="error-container" style="text-align: center; padding: 20px; border: 2px solid #d32f2f; border-radius: 8px; background-color: #ffebee; margin-bottom: 20px;">
                        <div style="color: #d32f2f; margin-bottom: 15px;">
                            <svg xmlns="http://www.w3.org/2000/svg" height="32px" viewBox="0 -960 960 960" width="32px" fill="#d32f2f" style="margin-bottom: 10px;">
                                <path d="M480-280q17 0 28.5-11.5T520-320q0-17-11.5-28.5T480-360q-17 0-28.5 11.5T440-320q0 17 11.5 28.5T480-280Zm-40-160h80v-240h-80v240Zm40 360q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-197q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Z"/>
                            </svg>
                            <h4 style="margin: 0; color: #d32f2f;">Error in Multiple Attribute Risk Scoring</h4>
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <p style="margin: 10px 0; font-size: 14px; color: #333;">
                                An error occurred while processing multiple attribute risk scores.
                            </p>
                            <p style="margin: 10px 0; font-size: 14px; color: #666;">
                                <strong>Error:</strong> ${content.errorDetails.errorMessage}
                            </p>
                        </div>
                    </div>
                `;
            } else if (content.isEntropyRisk) {
                // Simple error display for Entropy Risk (detailed info shown in popup)
                visualizationHtml += `
                    <div class="error-container" style="text-align: center; padding: 20px; border: 2px solid #d32f2f; border-radius: 8px; background-color: #ffebee; margin-bottom: 20px;">
                        <div style="color: #d32f2f; margin-bottom: 15px;">
                            <svg xmlns="http://www.w3.org/2000/svg" height="32px" viewBox="0 -960 960 960" width="32px" fill="#d32f2f" style="margin-bottom: 10px;">
                                <path d="M480-280q17 0 28.5-11.5T520-320q0-17-11.5-28.5T480-360q-17 0-28.5 11.5T440-320q0 17 11.5 28.5T480-280Zm-40-160h80v-240h-80v240Zm40 360q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-197q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Z"/>
                            </svg>
                            <h4 style="margin: 0; color: #d32f2f;">Error in Entropy Risk</h4>
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <p style="margin: 10px 0; font-size: 14px; color: #333;">
                                An error occurred while processing entropy risk.
                            </p>
                            <p style="margin: 10px 0; font-size: 14px; color: #666;">
                                <strong>Error:</strong> ${content.errorDetails.errorMessage}
                            </p>
                        </div>
                    </div>
                `;
            } else if (content.isKAnonymity) {
                // Simple error display for k-Anonymity (detailed info shown in popup)
                visualizationHtml += `
                    <div class="error-container" style="text-align: center; padding: 20px; border: 2px solid #d32f2f; border-radius: 8px; background-color: #ffebee; margin-bottom: 20px;">
                        <div style="color: #d32f2f; margin-bottom: 15px;">
                            <svg xmlns="http://www.w3.org/2000/svg" height="32px" viewBox="0 -960 960 960" width="32px" fill="#d32f2f" style="margin-bottom: 10px;">
                                <path d="M480-280q17 0 28.5-11.5T520-320q0-17-11.5-28.5T480-360q-17 0-28.5 11.5T440-320q0 17 11.5 28.5T480-280Zm-40-160h80v-240h-80v240Zm40 360q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-197q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Z"/>
                            </svg>
                            <h4 style="margin: 0; color: #d32f2f;">Error in k-Anonymity</h4>
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <p style="margin: 10px 0; font-size: 14px; color: #333;">
                                An error occurred while processing k-Anonymity.
                            </p>
                            <p style="margin: 10px 0; font-size: 14px; color: #666;">
                                <strong>Error:</strong> ${content.errorDetails.errorMessage}
                            </p>
                        </div>
                    </div>
                `;
            } else if (content.isLDiversity) {
                // Simple error display for l-Diversity (detailed info shown in popup)
                visualizationHtml += `
                    <div class="error-container" style="text-align: center; padding: 20px; border: 2px solid #d32f2f; border-radius: 8px; background-color: #ffebee; margin-bottom: 20px;">
                        <div style="color: #d32f2f; margin-bottom: 15px;">
                            <svg xmlns="http://www.w3.org/2000/svg" height="32px" viewBox="0 -960 960 960" width="32px" fill="#d32f2f" style="margin-bottom: 10px;">
                                <path d="M480-280q17 0 28.5-11.5T520-320q0-17-11.5-28.5T480-360q-17 0-28.5 11.5T440-320q0 17 11.5 28.5T480-280Zm-40-160h80v-240h-80v240Zm40 360q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-197q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Z"/>
                            </svg>
                            <h4 style="margin: 0; color: #d32f2f;">Error in l-Diversity</h4>
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <p style="margin: 10px 0; font-size: 14px; color: #333;">
                                An error occurred while processing l-Diversity.
                            </p>
                            <p style="margin: 10px 0; font-size: 14px; color: #666;">
                                <strong>Error:</strong> ${content.errorDetails.errorMessage}
                            </p>
                        </div>
                    </div>
                `;
            } else if (content.isTCloseness) {
                // Simple error display for t-Closeness (detailed info shown in popup)
                visualizationHtml += `
                    <div class="error-container" style="text-align: center; padding: 20px; border: 2px solid #d32f2f; border-radius: 8px; background-color: #ffebee; margin-bottom: 20px;">
                        <div style="color: #d32f2f; margin-bottom: 15px;">
                            <svg xmlns="http://www.w3.org/2000/svg" height="32px" viewBox="0 -960 960 960" width="32px" fill="#d32f2f" style="margin-bottom: 10px;">
                                <path d="M480-280q17 0 28.5-11.5T520-320q0-17-11.5-28.5T480-360q-17 0-28.5 11.5T440-320q0 17 11.5 28.5T480-280Zm-40-160h80v-240h-80v240Zm40 360q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-197q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Z"/>
                            </svg>
                            <h4 style="margin: 0; color: #d32f2f;">Error in t-Closeness</h4>
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <p style="margin: 10px 0; font-size: 14px; color: #333;">
                                An error occurred while processing t-Closeness.
                            </p>
                            <p style="margin: 10px 0; font-size: 14px; color: #666;">
                                <strong>Error:</strong> ${content.errorDetails.errorMessage}
                            </p>
                        </div>
                    </div>
                `;
            } else {
                // Standard error display for other metrics
                visualizationHtml += `<div style="text-align: center; padding: 20px; color: #d32f2f;">
                    <strong>Error:</strong> ${content.description}
                </div>`;
            }
        } else if (content.image && content.image.trim() !== "") {
            visualizationHtml += `<img src="${imageBlobUrl}" alt="Visualization ${index + 1} Chart">
            <a href="${imageBlobUrl}" download="${content.title}.jpg" class="toggle  metric-download" style="padding:0px;"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="currentColor"><path d="M480-320 280-520l56-58 104 104v-326h80v326l104-104 56 58-200 200ZM240-160q-33 0-56.5-23.5T160-240v-120h80v120h480v-120h80v120q0 33-23.5 56.5T720-160H240Z"/></svg></a>`;
        } else if (!content.isAsync) {
            // Display message for empty visualization (only for non-async tasks)
            visualizationHtml += `<div style="text-align: center; padding: 20px; color: #666;">
                No visualization available for this metric.
            </div>`;
        }
        
        // Special handling for Class Imbalance and Privacy metrics (your approach)
        if (content.isAsync) {
            // Create a unique ID for this async visualization
            const asyncId = `async-${content.taskId.replace(/[^a-zA-Z0-9]/g, '')}`;
            
            // Display async task status with progress bar in compatible structure
            visualizationHtml += `<div class="async-task-status" 
                 data-task-id="${content.taskId}" 
                 data-cache-key="${content.cacheKey}"
                 data-metric-name="${content.title}"
                 style="text-align: center; padding: 20px; border: 2px solid #2196F3; border-radius: 8px; background-color: #f8f9fa;">
                 
                <div style="margin-bottom: 15px;">
                    <h4 style="color: #1976D2; margin: 0 0 10px 0;">Results are being calculated...</h4>
                    <p style="color: #666; margin: 0; font-size: 14px;">This may take a few minutes. Please wait.</p>
                </div>
                
                <div class="progress-container" style="width: 100%; background-color: #e0e0e0; border-radius: 10px; height: 20px; overflow: hidden; margin-bottom: 15px;">
                    <div class="progress-bar" style="width: 0%; height: 100%; background: linear-gradient(90deg, #2196F3, #64B5F6); border-radius: 10px; transition: width 0.3s ease; animation: pulse 2s infinite;"></div>
                </div>
                
                <div style="font-size: 12px; color: #000;">
                    <span id="task-status-${content.taskId}">Processing...</span>
                </div>
                
                <style>
                    @keyframes pulse {
                        0% { opacity: 0.7; }
                        50% { opacity: 1; }
                        100% { opacity: 0.7; }
                    }
                </style>
            </div>`;
        } else {
            // Standard visualization display
            visualizationHtml += `
                    ${
                      content.riskScore !== "N/A"
                        ? `<div><strong>Risk Score:</strong> ${content.riskScore}</div>`
                        : ""
                    }
                    ${
                      content.value !== "N/A"
                        ? `<div><strong>${content.title}:</strong> ${content.value}</div>`
                        : ""
                    }
                   ${
                     !content.hasError && content.description
                       ? `<div><strong>Description:</strong> ${content.description}</div>`
                       : ""
                   }
                   ${
                     !content.hasError && content.interpretation
                       ? `<div><strong>Graph interpretation:</strong> ${content.interpretation}</div>`
                       : ""
                   }

                </div>

            </div>`;
        }

      metrics.innerHTML += visualizationHtml;
    });

    //check if duplicity is present and 0 (no duplicity)
    if (
      isKeyPresentAndDefined(data, "Duplicity") &&
      isKeyPresentAndDefined(data["Duplicity"], "Duplicity scores") &&
      data["Duplicity"]["Duplicity scores"][
        "Overall duplicity of the dataset"
      ] === 0
    ) {
      metrics.innerHTML += `<div class="visualization-container">
                <div class="toggle" style="display:block" onclick="toggleVisualization('duplicity')">
                    <div style="display: flex; justify-content:space-between; align-items: center;">
                        <div>Duplicity</div>
                        <svg id="duplicity-toggle-arrow" xmlns="http://www.w3.org/2000/svg" height="35px" viewBox="0 -960 960 960" width="36px" fill="currentColor"><path d="M480-360 280-560h400L480-360Z"/></svg>
                    </div>
                </div>
                <div id="duplicity" style="display: none;">
                    <p style="text-align:center">Overall Duplicity: ${data["Duplicity"]["Duplicity scores"]["Overall duplicity of the dataset"]}</p>
                </div>
            </div>`;
    } else if (
      isKeyPresentAndDefined(data, "Duplicity") &&
      isKeyPresentAndDefined(data["Duplicity"], "Duplicity scores")
    ) {
      metrics.innerHTML += `<div class="visualization-container">
                <div class="toggle" style="display:block" onclick="toggleVisualization('duplicity')">
                    <div style="display: flex; justify-content:space-between; align-items: center;">
                        <div>Duplicity</div>
                        <svg id="duplicity-toggle-arrow" xmlns="http://www.w3.org/2000/svg" height="35px" viewBox="0 -960 960 960" width="36px" fill="currentColor"><path d="M480-360 280-560h400L480-360Z"/></svg>
                    </div>
                </div>
                <div id="duplicity" style="display: none;">
                    <p style="text-align:center">Overall Duplicity: ${data["Duplicity"]["Duplicity scores"]["Overall duplicity of the dataset"]}</p>
                </div>
            </div>`;
    }

    // Assuming 'data' is your dictionary
    const modifiedData = removeVisualizationKey(data);
    const jsonBlobUrl = `data:application/json,${encodeURIComponent(
      JSON.stringify(modifiedData)
    )}`;
    // Add the "Download JSON" link for the last jsonData outside the loop
    metrics.innerHTML += `<a href="${jsonBlobUrl}" download="report.json" class="toggle">Download JSON Report</a>`;

    metrics.scrollIntoView({ behavior: "smooth" });
  } else {
    //check if duplicity is present and 0 (no duplicity)
    if (
      isKeyPresentAndDefined(data, "Duplicity") &&
      isKeyPresentAndDefined(data["Duplicity"], "Duplicity scores") &&
      data["Duplicity"]["Duplicity scores"][
        "Overall duplicity of the dataset"
      ] === 0
    ) {
      metrics.innerHTML = `<div class="heading">Readiness Report</div>`;
      metrics.innerHTML += `<div class="visualization-container">
                <div class="toggle" style="display:block" onclick="toggleVisualization('duplicity')">
                    <div style="display: flex; justify-content:space-between; align-items: center;">
                        <div>Duplicity</div>
                        <svg id="duplicity-toggle-arrow" xmlns="http://www.w3.org/2000/svg" height="35px" viewBox="0 -960 960 960" width="36px" fill="currentColor"><path d="M480-360 280-560h400L480-360Z"/></svg>
                    </div>
                </div>
                <div id="duplicity" style="display: none;">
                    No duplicates found
                </div>
            </div>`;
      metrics.scrollIntoView({ behavior: "smooth" });
    } else {
      metrics.innerHTML =
        '<h3 style="text-align:center;">No visualizations available.</h3>';
    }
    // Assuming 'data' is your dictionary
    const modifiedData = removeVisualizationKey(data);
    const jsonBlobUrl = `data:application/json,${encodeURIComponent(
      JSON.stringify(modifiedData)
    )}`;
    // Add the "Download JSON" link for the last jsonData outside the loop
    metrics.innerHTML += `<a href="${jsonBlobUrl}" download="report.json" class="toggle">Download JSON Report</a>`;
  }
})
.catch((error) => {
  console.error("Error:", error);
  openErrorPopup("Visualization Error", error); // call error popup

  // Check if "Completeness Visualization" key is present
  // if (isKeyPresentAndDefined(data, 'Completeness') && isKeyPresentAndDefined(data['Completeness'], 'Completeness Visualization')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="complVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Completeness']['Completeness Visualization'] + '" alt="Completeness Chart">' +
  //         '<div style="margin-left: 10px;">' +data['Completeness']['Description'] + '</div>' +
  //         '</div>';
  // }

  // Check if "Outliers Visualization" key is present
  // if (isKeyPresentAndDefined(data, 'Outliers') && isKeyPresentAndDefined(data['Outliers'], 'Outliers Visualization')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="outVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Outliers']['Outliers Visualization'] + '" alt="Outliers Chart">' +
  //         '<div style="margin-left: 10px;">' +data['Outliers']['Description'] + '</div>' +
  //         '</div>';
  // }

  // if (
  //     isKeyPresentAndDefined(data, 'Representation Rate') &&
  //     isKeyPresentAndDefined(data['Representation Rate'], 'Representation Rate Visualization')
  // ) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="repVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Representation Rate']['Representation Rate Chart']+ '" alt="Representation Rate Chart">' +
  //         '<div style="margin-left: 10px;">' +data['Representation Rate']['Description'] + '</div>' +
  //         '</div>';
  // }

  // if (isKeyPresentAndDefined(data, 'Statistical Rate') && isKeyPresentAndDefined(data['Statistical Rate'], 'Visualization')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="statRateVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Statistical Rate']['class_proportions_plot'] + '" alt="Statistical rate bar plot">' +
  //         '<div style="margin-left: 10px;">' +data['Statistical Rate']['Description'] + '</div>' +
  //         '</div>';
  // }

  // Check if "Representation Rate Comparison with Real World" key and "Comparisons" key are present
  // if (
  //     isKeyPresentAndDefined(data, 'Representation Rate Comparison with Real World') &&
  //     isKeyPresentAndDefined(data['Representation Rate Comparison with Real World']['Comparisons'], 'Comparison Visualization')
  // ) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="compVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Representation Rate Comparison with Real World']['Comparisons']['Comparison Visualization'] + '" alt="Comparisons Chart">' +
  //         '<div style="margin-left: 10px;">' +data['Representation Rate Comparison with Real World']['Description'] + '</div>' +
  //         '</div>';
  // }

  // if (isKeyPresentAndDefined(data, 'Correlations Analysis') && isKeyPresentAndDefined(data['Correlations Analysis'], 'Categorical-Categorical Visualization')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="catCorrVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Correlations Analysis']['Categorical-Categorical Correlation Matrix'] + '" alt="Categorical-Categorical Correlation Matrix">' +
  //         '<div style="margin-left: 10px;">' +data['Correlations Analysis']['cat_description'] + '</div>' +
  //         '</div>';

  // }

  // if (isKeyPresentAndDefined(data, 'Correlations Analysis') && isKeyPresentAndDefined(data['Correlations Analysis'], 'Numerical-Numerical Visualization')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="numCorrVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Correlations Analysis']['Numerical-Numerical Correlation Matrix'] + '" alt="Numerical-Numerical Correlation Matrix">' +
  //         '<div style="margin-left: 10px;">' +data['Correlations Analysis']['num_description'] + '</div>' +
  //         '</div>';

  // }

  // if (isKeyPresentAndDefined(data, 'Feature relevance') && isKeyPresentAndDefined(data['Feature relevance'], 'Feature relevance Visualization')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="featureRelVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Feature relevance']['summary plot'] + '" alt="Shapley value plot">' +
  //         '<div style="margin-left: 10px;">' +data['Feature relevance']['Description'] + '</div>' +
  //         '</div>';
  // }
  // if (isKeyPresentAndDefined(data, 'Class imbalance') && isKeyPresentAndDefined(data['Class imbalance'], 'Class distribution plot')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="classDisVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Class imbalance']['Class distribution plot'] + '" alt="Class distribution plot">' +
  //         '<div style="margin-left: 10px;">' +data['Class imbalance']['Description'] + '</div>' +
  //         '</div>';
  // }

  // if (isKeyPresentAndDefined(data, 'DP statistics') && isKeyPresentAndDefined(data['DP statistics'], 'Combined Plots')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="noisyVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['DP statistics']['Combined Plots'] + '" alt="Normal vs Noisy Feature Box Plots">' +
  //         '<div style="margin-left: 10px;">' +data['DP statistics']['Description'] + '</div>' +
  //         '</div>';
  // }

  // if (isKeyPresentAndDefined(data, 'Single attribute risk scoring') && isKeyPresentAndDefined(data['Single attribute risk scoring'], 'BoxPlot')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="singleRiskVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Single attribute risk scoring']['BoxPlot'] + '" alt="Single attribute risk score box plots">'+
  //         '<div style="margin-left: 10px;">' +data['Single attribute risk scoring']['Description'] + '</div>' +
  //         '</div>'

  // }
  // if (isKeyPresentAndDefined(data, 'Multiple attribute risk scoring') && isKeyPresentAndDefined(data['Multiple attribute risk scoring'], 'Box Plot')) {
  //     // Display the chart image and description in a single div
  //     resultContainer.innerHTML += '<div id="multipleRiskVis" style="display:none; text-align: left;">' +
  //         '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Multiple attribute risk scoring']['Box Plot'] + '" alt="Multiple attribute risk score box plots">'+
  //         '<div style="margin-left: 10px;">' +data['Multiple attribute risk scoring']['Description'] + '</div>' +
  //         '</div>'

  // }

  //Display other result information as JSON
  // if (data['Duplicity'] && data['Duplicity']['Duplicity scores'] && data['Duplicity']['Duplicity scores']['Overall duplicity of the dataset'] !== undefined) {
  //     resultContainer.innerHTML += '<div id="duplicityScoreResult" style="display:none"> <h3> Duplicity Scores </h3>'+
  //         '<pre> Overall Duplicity: ' + data['Duplicity']['Duplicity scores']['Overall duplicity of the dataset'] + '</pre>' +
  //         '</div>';
  // }

  // if (data['Class imbalance'] && data['Class imbalance']['Imbalance degree'] && data['Class imbalance']['Imbalance degree']['Imbalance degree score'] !== undefined) {
  //     resultContainer.innerHTML += '<div id="imbalanceScoreResult" style="display:none"> <h3> Class Imbalance Scores </h3>'+
  //         '<pre> Imbalance degree: ' + data['Class imbalance']['Imbalance degree']['Imbalance degree score'] + '</pre>' +
  //         '</div>';
  // }

  // resultContainer.innerHTML += '<pre id="scoreResult" style="display:none;">' + data['Duplicity']['Duplicity scores']['Overall duplicity of the dataset'] + '</pre>';
})
.catch((error) => {
  console.error("Error:", error);
  openErrorPopup("", error); // call error popup
});
}

function removeVisualizationKey(data) {
  for (let key in data) {
    if (typeof data[key] === "object" && data[key] !== null) {
      // If the value is an object, recursively call removeVisualizationKey
      data[key] = removeVisualizationKey(data[key]);
    } else if (key.endsWith(" Visualization")) {
      // If the key is 'Completeness Visualization', remove it
      delete data[key];
    }
  }
  return data;
}

// Documentation button function for privacy metrics (your approach)
function getDocsButton(title) {
    const anchorMap = {
        'DP Statistics': '#differential-privacy',
        'Single attribute risk scoring': '#single-attribute-risk',
        'Multiple attribute risk scoring': '#multiple-attribute-risk',
        'Entropy Risk': '#entropy-risk',
        'k-Anonymity': '#k-anonymity',
        'l-Diversity': '#l-diversity',
        't-Closeness': '#t-closeness',
    };
    const anchor = anchorMap[title] || '';
    if (!anchor) return '';
    return `<a href="/privacy-metrics-docs${anchor}" target="_blank" style="margin-left:10px; color:#4a90e2; font-style:italic;">See documentation</a>`;
}

// Distance metric name function for Class Imbalance (your approach)
function getDistanceMetricName() {
    // Get the selected distance metric from the form
    const distanceSelect = document.getElementById('distance-metric');
    if (distanceSelect) {
        const selectedValue = distanceSelect.value;
        const metricNames = {
            'EU': 'Euclidean Distance',
            'CH': 'Chebyshev Distance', 
            'KL': 'KL Divergence',
            'HE': 'Hellinger Distance',
            'TV': 'Total Variation Distance',
            'CS': 'Chi-Squared Distance'
        };
        return metricNames[selectedValue] || 'Distance Metric';
    }
    return 'Distance Metric';
}

// Async task polling for MMrisk score calculations
function pollAsyncTask(taskId, cacheKey, metricName, maxAttempts = 800, interval = 1500) {
    let attempts = 0;
    
    console.log(`Starting polling for ${metricName} task: ${taskId}`);
    
    function checkTask() {
        attempts++;
        
        fetch(`/check_and_update_task/${taskId}/${encodeURIComponent(metricName)}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {

                
                // Get DOM elements for progress bar and status
                const asyncTaskElement = document.querySelector(`[data-task-id="${taskId}"]`);
                const statusSpan = asyncTaskElement ? asyncTaskElement.querySelector(`#task-status-${taskId}`) : null;
                const progressBar = asyncTaskElement ? asyncTaskElement.querySelector('.progress-bar') : null;
                
                if (data.status === 'completed' || data.status === 'SUCCESS') {

                    
                    // Task completed successfully, complete the progress bar
                    if (progressBar) {
                        progressBar.style.width = '100%';
                        progressBar.style.background = 'linear-gradient(90deg, #4CAF50, #8BC34A)';
                    }
                    
                    if (statusSpan) {
                        statusSpan.textContent = 'Calculation completed!';
                    }
                    
                    // Wait a moment to show completion, then update with results
                    setTimeout(() => {
                        updateAsyncTaskWithResults(taskId, metricName, data.result);
                    }, 1000);
                    return; // Exit polling
                }
                
                // Update progress bar and status from real Celery data
                if (data.progress) {
                    const realProgress = data.progress.current || 0;
                    const realStatus = data.progress.status || 'Processing...';
                    
                    if (progressBar) {
                        progressBar.style.width = `${realProgress}%`;
                        // Update progress bar color based on stage
                        if (realProgress < 30) {
                            progressBar.style.background = 'linear-gradient(90deg, #2196F3, #64B5F6)'; // Blue - preprocessing
                        } else if (realProgress < 70) {
                            progressBar.style.background = 'linear-gradient(90deg, #FF9800, #FFB74D)'; // Orange - calculation
                        } else if (realProgress < 90) {
                            progressBar.style.background = 'linear-gradient(90deg, #9C27B0, #BA68C8)'; // Purple - statistics
                        } else {
                            progressBar.style.background = 'linear-gradient(90deg, #4CAF50, #8BC34A)'; // Green - visualization
                        }
                    }
                    
                    if (statusSpan) {
                        const timeElapsed = Math.round((attempts * interval) / 1000);
                        statusSpan.textContent = `${realStatus} (${timeElapsed}s elapsed)`;
                    }
                }
                
                // Continue polling if not complete
                if (attempts < maxAttempts) {
                    setTimeout(checkTask, interval);
                } else {
                    // Timeout reached
                    if (progressBar) {
                        progressBar.style.background = 'linear-gradient(90deg, #FF9800, #FFB74D)';
                    }
                    if (statusSpan) {
                        statusSpan.textContent = 'Taking longer than expected...';
                    }
                    console.warn(`${metricName} polling timeout reached. Task may still be running.`);
                }
            })
            .catch(error => {
                console.error('Polling error:', error);
                if (attempts < maxAttempts) {
                    setTimeout(checkTask, interval);
                } else {
                    // Max retries reached
                    const asyncTaskElement = document.querySelector(`[data-task-id="${taskId}"]`);
                    const progressBar = asyncTaskElement ? asyncTaskElement.querySelector('.progress-bar') : null;
                    const statusSpan = asyncTaskElement ? asyncTaskElement.querySelector(`#task-status-${taskId}`) : null;
                    
                    if (progressBar) {
                        progressBar.style.background = 'linear-gradient(90deg, #F44336, #E57373)';
                    }
                    if (statusSpan) {
                        statusSpan.textContent = 'Connection error';
                    }
                }
            });
    }
    
    // Start polling
    checkTask();
}

function updateAsyncTaskWithResults(taskId, metricName, results) {
    // Find the async task placeholder
    const asyncElement = document.querySelector(`[data-task-id="${taskId}"]`);
    updateTaskStatus(taskId, metricName, 'completed', 'Calculation completed!');
    if (!asyncElement || !results) {
        console.log('No async element or results found:', { taskId, metricName, results });
        return;
    }



    // Build the completed visualization HTML
    let completedHtml = '';
    
    // Check if there's an error
    if (results.error) {
        completedHtml = `
            <div style="text-align: center; padding: 20px; color: #d32f2f;">
                <strong>Error:</strong> ${results.error}
            </div>`;
    } else {
        // Add visualization image if present - try multiple possible keys
        const possibleVizKeys = [
            `${metricName} Visualization`,
            "Multiple attribute risk scoring Visualization",
            "Single attribute risk scoring Visualization"
        ];
        

        
        let vizKey = null;
        for (const key of possibleVizKeys) {
            if (results[key] && results[key].trim() !== "") {
                vizKey = key;

                break;
            }
        }
        
        if (vizKey) {
            completedHtml += `
                <div class="visualization-container">
                    <img src="data:image/png;base64,${results[vizKey]}" 
                         alt="Risk Score Visualization" 
                         style="max-width: 100%; height: auto;">
                </div>`;
        } else {

        }

        // Add description if present
        if (results.Description) {
            completedHtml += `<div style="color: inherit;"><strong>Description:</strong> ${results.Description}</div>`;
        }

        // Add graph interpretation if present
        if (results["Graph interpretation"]) {
            completedHtml += `<div style="color: inherit;"><strong>Graph interpretation:</strong> ${results["Graph interpretation"]}</div>`;
        }

        // Add statistics if present
        if (results["Descriptive statistics of the risk scores"]) {
            const stats = results["Descriptive statistics of the risk scores"];
            
            // Check if stats is for single attribute (object with feature names as keys) or multiple attribute (single object)
            if (typeof stats === 'object' && stats !== null && !stats.hasOwnProperty('mean')) {
                // Single attribute: stats is {feature1: {mean, std, ...}, feature2: {mean, std, ...}, ...}
                completedHtml += `
                    <div class="statistics-container" style="margin-bottom: 20px; color: inherit;">
                        <h4 style="color: inherit; margin-bottom: 10px; font-weight: bold;">Descriptive Statistics</h4>
                        <table class="table table-bordered" style="color: inherit; background-color: transparent; border-color: inherit;">
                            <tr>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Feature</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Mean</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Std</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Min</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">25%</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">50%</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">75%</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Max</th>
                            </tr>`;
                
                // Add a row for each feature
                for (const [featureName, featureStats] of Object.entries(stats)) {
                    completedHtml += `
                        <tr>
                            <td style="color: inherit; background-color: transparent; border-color: inherit;"><strong>${featureName}</strong></td>
                            <td style="color: inherit; background-color: transparent; border-color: inherit;">${featureStats.mean.toFixed(3)}</td>
                            <td style="color: inherit; background-color: transparent; border-color: inherit;">${featureStats.std.toFixed(3)}</td>
                            <td style="color: inherit; background-color: transparent; border-color: inherit;">${featureStats.min.toFixed(3)}</td>
                            <td style="color: inherit; background-color: transparent; border-color: inherit;">${featureStats["25%"].toFixed(3)}</td>
                            <td style="color: inherit; background-color: transparent; border-color: inherit;">${featureStats["50%"].toFixed(3)}</td>
                            <td style="color: inherit; background-color: transparent; border-color: inherit;">${featureStats["75%"].toFixed(3)}</td>
                            <td style="color: inherit; background-color: transparent; border-color: inherit;">${featureStats.max.toFixed(3)}</td>
                        </tr>`;
                }
                
                completedHtml += `</table></div>`;
            } else {
                // Multiple attribute: stats is a single object {mean, std, min, ...}
                completedHtml += `
                    <div class="statistics-container" style="margin-bottom: 20px; color: inherit;">
                        <h4 style="color: inherit; margin-bottom: 10px; font-weight: bold;">Descriptive Statistics</h4>
                        <table class="table table-bordered" style="color: inherit; background-color: transparent; border-color: inherit;">
                            <tr>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Mean</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Std</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Min</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">25%</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">50%</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">75%</th>
                                <th style="color: inherit; background-color: transparent; border-color: inherit;">Max</th>
                            </tr>
                            <tr>
                                <td style="color: inherit; background-color: transparent; border-color: inherit;">${stats.mean.toFixed(3)}</td>
                                <td style="color: inherit; background-color: transparent; border-color: inherit;">${stats.std.toFixed(3)}</td>
                                <td style="color: inherit; background-color: transparent; border-color: inherit;">${stats.min.toFixed(3)}</td>
                                <td style="color: inherit; background-color: transparent; border-color: inherit;">${stats["25%"].toFixed(3)}</td>
                                <td style="color: inherit; background-color: transparent; border-color: inherit;">${stats["50%"].toFixed(3)}</td>
                                <td style="color: inherit; background-color: transparent; border-color: inherit;">${stats["75%"].toFixed(3)}</td>
                                <td style="color: inherit; background-color: transparent; border-color: inherit;">${stats.max.toFixed(3)}</td>
                            </tr>
                        </table>
                    </div>`;
            }
        }
    }

    // Replace the progress bar with the completed content
    if (completedHtml) {
        // Remove the custom background styling so it inherits from the plot-container
        asyncElement.style.background = 'none';
        asyncElement.style.border = 'none';
        asyncElement.style.borderRadius = '0';
        asyncElement.style.padding = '0';
        asyncElement.style.textAlign = 'left';
        
        // Replace the content
        asyncElement.innerHTML = completedHtml;
    }
}

function updateTaskStatus(taskId, metricName, status, message) {
    // Find the async task status element for this metric
    const asyncElements = document.querySelectorAll(`[data-metric-name="${metricName}"]`);
    
    if (asyncElements.length > 0) {
        asyncElements.forEach(element => {
            // Update the status display
            const statusP = element.querySelector('p:first-child');
            const messageP = element.querySelector('p:nth-child(2)');
            
            if (statusP) {
                statusP.innerHTML = `<strong>Status:</strong> ${status}`;
            }
            if (messageP) {
                messageP.innerHTML = `<em>${message}</em>`;
            }
            
            // If task completed successfully, hide the spinner
            if (status === 'SUCCESS' || status === 'COMPLETED') {
                const spinner = element.querySelector('.progress-indicator');
                if (spinner) {
                    spinner.style.display = 'none';
                }
            }
        });
    } else {
        // Final fallback: add status to page
        console.log(`Task Status Update - ${metricName}: ${status} - ${message}`);
    }
}




// Modify the function to accept an array of visualization content
// function showVis(visualizationContent) {
//     // Create a new popup window
//     var popup = window.open("", "Popup", "width=1000,height=1000,resizable=yes,scrollbars=yes");

//     // Ensure the popup window is fully loaded before writing content
//     popup.onload = function() {
//         // Write HTML and CSS into the popup window
//         popup.document.write(`
//             <html>
//             <head>
//                 <title>Visualizations</title>
//                 <style>
//                     body {
//                         font-family: Arial, sans-serif;
//                         padding: 20px;
//                         background-color: #f9f9f9;
//                     }
//                     .visualization-container {
//                         margin-bottom: 20px;
//                     }
//                     .visualization-container img {
//                         max-width: 100%;
//                         border-radius: 4px;
//                         margin-bottom: 10px;
//                     }
//                     .visualization-container div {
//                         color: #333;
//                         font-size: 20px;
//                     }
//                     .download-button {
//                         display: inline-block;
//                         padding: 10px 20px;
//                         margin-bottom: 10px;
//                         background-color: #007bff;
//                         color: white;
//                         text-decoration: none;
//                         border-radius: 4px;
//                         font-size: 14px;
//                     }
//                 </style>
//             </head>
//             <body>
//         `);

//         visualizationContent.forEach(function(content, index) {
//             const imageBlobUrl = `data:image/jpeg;base64,${content.image}`;
//             popup.document.write(`
//                 <div class="visualization-container">
//                     <img src="${imageBlobUrl}" alt="Visualization ${index + 1} Chart">
//                     <a href="${imageBlobUrl}" download="Visualization_${index + 1}.jpg" class="download-button">Download</a>

//                     <div>${content.description}</div>
//                 </div>
//             `);
//         });

//         // Close the HTML document
//         popup.document.write('</body></html>');

//         // Close the document to render the content
//         popup.document.close();
//     };
// }

// function showVisualization() {

//     // Get Completeness Visualization content
//     var completenessContent = document.getElementById('complVis');

//     if (completenessContent) {
//         // Reduce the size of the image
//         completenessContent.style.width = '600px'; // Set a fixed width
//         completenessContent.style.height = 'auto'; // Let the height adjust proportionally

//         completenessContent.style.display = 'flex';
//         completenessContent.style.flexDirection = 'column';
//         // completenessContent.style.alignItems = 'center';
//         completenessContent.style.border = '1px solid #ddd'; // Add a border
//         completenessContent.style.borderRadius = '8px'; // Add rounded corners
//         completenessContent.style.padding = '10px'; // Add some padding
//         completenessContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         completenessContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         completenessContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         completenessContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         completenessContent.querySelector('div').style.color = '#333'; // Set text color
//         completenessContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         completenessContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

//     // Show Outliers Visualization content if it exists
//     var outliersContent = document.getElementById('outVis');
//     if (outliersContent) {

//         // Reduce the size of the image
//         outliersContent.style.width = '600px'; // Set a fixed width
//         outliersContent.style.height = 'auto'; // Let the height adjust proportionally

//         outliersContent.style.display = 'flex';
//         outliersContent.style.flexDirection = 'column';
//         outliersContent.style.alignItems = 'center';
//         outliersContent.style.border = '1px solid #ddd'; // Add a border
//         outliersContent.style.borderRadius = '8px'; // Add rounded corners
//         outliersContent.style.padding = '10px'; // Add some padding
//         outliersContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         outliersContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         outliersContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         outliersContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         outliersContent.querySelector('div').style.color = '#333'; // Set text color
//         outliersContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         outliersContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

//     // Show Representation Rate Visualization content if it exists
//     var representationRateContent = document.getElementById('repVis');
//     if (representationRateContent) {

//         // Reduce the size of the image
//         representationRateContent.style.width = '600px'; // Set a fixed width
//         representationRateContent.style.height = 'auto'; // Let the height adjust proportionally

//         representationRateContent.style.display = 'flex';
//         representationRateContent.style.flexDirection = 'column';
//         // representationRateContent.style.alignItems = 'center';
//         representationRateContent.style.border = '1px solid #ddd'; // Add a border
//         representationRateContent.style.borderRadius = '8px'; // Add rounded corners
//         representationRateContent.style.padding = '10px'; // Add some padding
//         representationRateContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         representationRateContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         representationRateContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         representationRateContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         representationRateContent.querySelector('div').style.color = '#333'; // Set text color
//         representationRateContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         representationRateContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

//     // Show Comparison Visualization content if it exists
//     var comparisonContent = document.getElementById('compVis');
//     if (comparisonContent) {

//         // Reduce the size of the image
//         comparisonContent.style.width = '600px'; // Set a fixed width
//         comparisonContent.style.height = 'auto'; // Let the height adjust proportionally

//         comparisonContent.style.display = 'flex';
//         comparisonContent.style.flexDirection = 'column';


//         // comparisonContent.style.alignItems = 'center';
//         comparisonContent.style.border = '1px solid #ddd'; // Add a border
//         comparisonContent.style.borderRadius = '8px'; // Add rounded corners
//         comparisonContent.style.padding = '10px'; // Add some padding
//         comparisonContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         comparisonContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         comparisonContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         comparisonContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         comparisonContent.querySelector('div').style.color = '#333'; // Set text color
//         comparisonContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         comparisonContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

//     // Statistical Rate Visualization content if it exists
//     var stateRateVis = document.getElementById('statRateVis');
//     if (stateRateVis) {

//         // Reduce the size of the image
//         stateRateVis.style.width = '600px'; // Set a fixed width
//         stateRateVis.style.height = 'auto'; // Let the height adjust proportionally

//         stateRateVis.style.display = 'flex';
//         stateRateVis.style.flexDirection = 'column';


//         // stateRateVis.style.display = 'flex';
//         // stateRateVis.style.alignItems = 'center';
//         stateRateVis.style.border = '1px solid #ddd'; // Add a border
//         stateRateVis.style.borderRadius = '8px'; // Add rounded corners
//         stateRateVis.style.padding = '10px'; // Add some padding
//         stateRateVis.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         stateRateVis.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         stateRateVis.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         stateRateVis.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         stateRateVis.querySelector('div').style.color = '#333'; // Set text color
//         stateRateVis.querySelector('div').style.fontSize = '20px'; // Set font size
//         stateRateVis.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }
//     // Show Correlation Visualization content if it exists
//     var catCorrContent = document.getElementById('catCorrVis');
//     if (catCorrContent) {

//         // Reduce the size of the image
//         catCorrContent.style.width = '600px'; // Set a fixed width
//         catCorrContent.style.height = 'auto'; // Let the height adjust proportionally

//         catCorrContent.style.display = 'flex';
//         catCorrContent.style.flexDirection = 'column';

//         // catCorrContent.style.display = 'flex';
//         // catCorrContent.style.alignItems = 'center';
//         catCorrContent.style.border = '1px solid #ddd'; // Add a border
//         catCorrContent.style.borderRadius = '8px'; // Add rounded corners
//         catCorrContent.style.padding = '10px'; // Add some padding
//         catCorrContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         catCorrContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         catCorrContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         catCorrContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         catCorrContent.querySelector('div').style.color = '#333'; // Set text color
//         catCorrContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         catCorrContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

//     var numCorrContent = document.getElementById('numCorrVis');
//     if (numCorrContent) {

//         // Reduce the size of the image
//         numCorrContent.style.width = '600px'; // Set a fixed width
//         numCorrContent.style.height = 'auto'; // Let the height adjust proportionally

//         numCorrContent.style.display = 'flex';
//         numCorrContent.style.flexDirection = 'column';

//         // numCorrContent.style.display = 'flex';
//         // numCorrContent.style.alignItems = 'center';
//         numCorrContent.style.border = '1px solid #ddd'; // Add a border
//         numCorrContent.style.borderRadius = '8px'; // Add rounded corners
//         numCorrContent.style.padding = '10px'; // Add some padding
//         numCorrContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         numCorrContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         numCorrContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         numCorrContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         numCorrContent.querySelector('div').style.color = '#333'; // Set text color
//         numCorrContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         numCorrContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }


//     var featureRelContent = document.getElementById('featureRelVis');
//     if (featureRelContent) {

//         // Reduce the size of the image
//         featureRelContent.style.width = '600px'; // Set a fixed width
//         featureRelContent.style.height = 'auto'; // Let the height adjust proportionally

//         featureRelContent.style.display = 'flex';
//         featureRelContent.style.flexDirection = 'column';

//         // featureRelContent.style.display = 'flex';
//         // featureRelContent.style.alignItems = 'center';
//         featureRelContent.style.border = '1px solid #ddd'; // Add a border
//         featureRelContent.style.borderRadius = '8px'; // Add rounded corners
//         featureRelContent.style.padding = '10px'; // Add some padding
//         featureRelContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         featureRelContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         featureRelContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         featureRelContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         featureRelContent.querySelector('div').style.color = '#333'; // Set text color
//         featureRelContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         featureRelContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

//     var classImbalanceContent = document.getElementById('classDisVis');
//     if (classImbalanceContent) {

//         // Reduce the size of the image
//         classImbalanceContent.style.width = '600px'; // Set a fixed width
//         classImbalanceContent.style.height = 'auto'; // Let the height adjust proportionally

//         classImbalanceContent.style.display = 'flex';
//         classImbalanceContent.style.flexDirection = 'column';

//         // classImbalanceContent.style.display = 'flex';
//         // classImbalanceContent.style.alignItems = 'center';
//         classImbalanceContent.style.border = '1px solid #ddd'; // Add a border
//         classImbalanceContent.style.borderRadius = '8px'; // Add rounded corners
//         classImbalanceContent.style.padding = '10px'; // Add some padding
//         classImbalanceContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         classImbalanceContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         classImbalanceContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         classImbalanceContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         classImbalanceContent.querySelector('div').style.color = '#333'; // Set text color
//         classImbalanceContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         classImbalanceContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

//     // Show Normal vs Noisy Feature Visualization content if it exists
//     var noisyContent = document.getElementById('noisyVis');
//     if (noisyContent) {

//         // Reduce the size of the image
//         noisyContent.style.width = '600px'; // Set a fixed width
//         noisyContent.style.height = 'auto'; // Let the height adjust proportionally

//         noisyContent.style.display = 'flex';
//         noisyContent.style.flexDirection = 'column';

//         // noisyContent.style.display = 'flex';
//         // noisyContent.style.alignItems = 'center';
//         noisyContent.style.border = '1px solid #ddd'; // Add a border
//         noisyContent.style.borderRadius = '8px'; // Add rounded corners
//         noisyContent.style.padding = '10px'; // Add some padding
//         noisyContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         noisyContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         noisyContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         noisyContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         noisyContent.querySelector('div').style.color = '#333'; // Set text color
//         noisyContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         noisyContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }


//      // Show single attribute risk scores
//      var singleRiskContent = document.getElementById('singleRiskVis');
//     if (singleRiskContent) {

//         // Reduce the size of the image
//         singleRiskContent.style.width = '600px'; // Set a fixed width
//         singleRiskContent.style.height = 'auto'; // Let the height adjust proportionally

//         singleRiskContent.style.display = 'flex';
//         singleRiskContent.style.flexDirection = 'column';

//         // singleRiskContent.style.display = 'flex';
//         // singleRiskContent.style.alignItems = 'center';
//         singleRiskContent.style.border = '1px solid #ddd'; // Add a border
//         singleRiskContent.style.borderRadius = '8px'; // Add rounded corners
//         singleRiskContent.style.padding = '10px'; // Add some padding
//         singleRiskContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         singleRiskContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         singleRiskContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         singleRiskContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         singleRiskContent.querySelector('div').style.color = '#333'; // Set text color
//         singleRiskContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         singleRiskContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

//     // Show multiple attribute risk scores
//     var multipleRiskContent = document.getElementById('multipleRiskVis');
//     if (multipleRiskContent) {

//         // Reduce the size of the image
//         multipleRiskContent.style.width = '600px'; // Set a fixed width
//         multipleRiskContent.style.height = 'auto'; // Let the height adjust proportionally

//         multipleRiskContent.style.display = 'flex';
//         multipleRiskContent.style.flexDirection = 'column';

//         // multipleRiskContent.style.display = 'flex';
//         // multipleRiskContent.style.alignItems = 'center';
//         multipleRiskContent.style.border = '1px solid #ddd'; // Add a border
//         multipleRiskContent.style.borderRadius = '8px'; // Add rounded corners
//         multipleRiskContent.style.padding = '10px'; // Add some padding
//         multipleRiskContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

//         // Styles for the image
//         multipleRiskContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
//         multipleRiskContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

//         // Styles for the description
//         multipleRiskContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
//         multipleRiskContent.querySelector('div').style.color = '#333'; // Set text color
//         multipleRiskContent.querySelector('div').style.fontSize = '20px'; // Set font size
//         multipleRiskContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
//     }

    


//     // Hide JSON content
//     var scoreResult = document.getElementById('scoreResult');
//     if (scoreResult) {
//         scoreResult.style.display = 'none';
//     }
// }

function downloadJSON() {
  // Get the JSON data
  var jsonData = JSON.stringify(resp_data, null, 2);

  // Create a Blob with the JSON data
  var blob = new Blob([jsonData], { type: "application/json" });

  // Create a link element
  var link = document.createElement("a");

  // Set the link's href attribute to a data URL containing the Blob
  link.href = window.URL.createObjectURL(blob);

  // Set the link's download attribute to specify the file name
  link.download = "result.json";

  // Append the link to the document
  document.body.appendChild(link);

  // Trigger a click on the link to start the download
  link.click();

  // Remove the link from the document
  document.body.removeChild(link);
}

function showResults() {
  // Show Duplicity Visualization content if it exists
  var duplicityScoreResult = document.getElementById("duplicityScoreResult");
  if (duplicityScoreResult) {
    duplicityScoreResult.style.display = "block";
  }
  var imbalanceScoreResult = document.getElementById("imbalanceScoreResult");
  if (imbalanceScoreResult) {
    imbalanceScoreResult.style.display = "block";
  }
}

// function toggleCheckboxes(sectionId, sectionTag, innertext) {
//     var checkboxContainer = document.getElementById(sectionId);
//     var toggleButton = document.getElementById("toggleButton_" + sectionTag);

//     // Check if the button exists, if not, create it
//     if (!toggleButton) {
//         toggleButton = document.createElement("button");
//         toggleButton.id = "toggleButton_" + sectionTag;
//         toggleButton.innerText = "+";
//         toggleButton.style.cursor = "pointer";
//         toggleButton.addEventListener("click", function() {
//             toggleCheckboxContainer(checkboxContainer, toggleButton, innertext); // Pass toggleButton as an argument
//         });
//         // Append the button to the container
//         checkboxContainer.parentNode.insertBefore(toggleButton, checkboxContainer);
//     }

//     toggleCheckboxContainer(checkboxContainer, toggleButton, innertext); // Pass toggleButton as an argument
// }

// function toggleCheckboxContainer(checkboxContainer, toggleButton, innertext) {
//     var isExpanded = checkboxContainer.style.display === "block";

//     if (isExpanded) {
//         checkboxContainer.style.display = "none";
//         toggleButton.innerText = "+ "+ innertext;
//         toggleButton.style.cursor = "pointer";
//     } else {
//         checkboxContainer.style.display = "block";
//         toggleButton.innerText = "- " + innertext;
//         toggleButton.style.cursor = "pointer";
//     }
// }

function toggleValue(checkbox) {
  console.log("Checkbox clicked:", checkbox);
  // Find the closest parent container of the checkbox (checkboxContainer)
  const container = checkbox.closest(".checkboxContainerIndividual");
  console.log(container);

     if (!container) {
         return;
     }
     console.log("Container found:", container);
     
     // Toggle the metric-selected class to show/hide QI sections
     if (checkbox.checked) {
         container.classList.add('metric-selected');
         console.log("Added metric-selected class - QI sections should be visible");
     } else {
         container.classList.remove('metric-selected');
         console.log("Removed metric-selected class - QI sections should be hidden");
     }
     
     // Find all select dropdowns within that container
     const dropdowns = container.querySelectorAll("select");
     const inputs = container.querySelectorAll("input.textWrapper");
     const checkboxes = container.querySelectorAll("input.checkbox.individual");
     // Enable or disable all dropdowns inside the container based on checkbox state
     dropdowns.forEach(dropdown => {
         dropdown.disabled = !checkbox.checked; 
     });
     inputs.forEach(input => {
         input.disabled = !checkbox.checked; 
     });
     checkboxes.forEach(input => {
        input.disabled = !checkbox.checked; 
    });
    // Toggle the value based on the checked state
    if (checkbox.checked) {
        checkbox.value = "yes";
    } else {
        checkbox.value = "no";
    }
    console.log("Checkbox value:", checkbox.value); // For debugging
}
function toggleValueIndividual(checkbox) {
  // Toggle the value based on the checked state
  if (checkbox.checked) {
    const label = checkbox.closest("label");
    const text = label.textContent.trim();
    checkbox.value = text;
  } else {
    checkbox.value = "no";
  }
  updateSelectAllState();
  console.log("Checkbox value:", checkbox.value); // For debugging
}
function updateSelectAllState() {
  const checkboxes = document.querySelectorAll(".checkbox.individual");
  const selectAll = document.getElementById("selectAllCheckbox");

  const total = checkboxes.length;
  const checked = Array.from(checkboxes).filter((cb) => cb.checked).length;

  if (checked === 0) {
    selectAll.checked = false;
  } else if (checked === total) {
    selectAll.checked = true;
  } else {
    selectAll.checked = false;
  }
}
// Ensure proper initial state on page load
document.addEventListener("DOMContentLoaded", function() {
  // Get all checkboxes inside each checkboxContainer
    document.querySelectorAll(".checkboxContainer").forEach(container => {
    const checkboxes = container.querySelectorAll("input[type='checkbox']");
        checkboxes.forEach(checkbox => {
      console.log(checkbox);
      // Set initial state of selects based on checkbox
      toggleValue(checkbox);
    });
    });
    
    // Also handle checkboxContainerIndividual containers for privacy preservation
    document.querySelectorAll(".checkboxContainerIndividual").forEach(container => {
        const checkboxes = container.querySelectorAll("input[type='checkbox']");
        checkboxes.forEach(checkbox => {
            console.log(checkbox);
            // Set initial state of selects based on checkbox
            toggleValue(checkbox);
        });
    });

// Auto-start polling for async tasks when page loads
    console.log('DOMContentLoaded: Checking for async tasks...');
    
    // Check if there are any async tasks that need polling
    const scripts = document.querySelectorAll('script[data-task-id]');
    console.log('Found', scripts.length, 'scripts with task IDs');
    
    scripts.forEach(script => {
        const taskId = script.getAttribute('data-task-id');
        const cacheKey = script.getAttribute('data-cache-key');
        const metricName = script.getAttribute('data-metric-name');
        
        console.log('Script attributes:', { taskId, cacheKey, metricName });
        
        if (taskId && cacheKey && metricName) {
    
            pollAsyncTask(taskId, cacheKey, metricName);
        }
    });
    
    // Also check for any elements that contain async task information in the results
    const resultElements = document.querySelectorAll('[data-task-id]');
    console.log('Found', resultElements.length, 'result elements with task IDs');
    
    resultElements.forEach(element => {
        const taskId = element.getAttribute('data-task-id');
        const cacheKey = element.getAttribute('data-cache-key');
        const metricName = element.getAttribute('data-metric-name') || 'MMrisk Score';
        
        if (taskId && cacheKey) {
            console.log(`Starting polling for ${metricName} from result element: ${taskId}`);
            pollAsyncTask(taskId, cacheKey, metricName);
        }
    });
    
    // Also check for async task status elements specifically
    const asyncStatusElements = document.querySelectorAll('.async-task-status[data-task-id]');
    console.log('Found', asyncStatusElements.length, 'async status elements');
    
    asyncStatusElements.forEach(element => {
        const taskId = element.getAttribute('data-task-id');
        const cacheKey = element.getAttribute('data-cache-key');
        const metricName = element.getAttribute('data-metric-name') || 'MMrisk Score';
        
        if (taskId && cacheKey) {
            console.log(`Starting polling for ${metricName} from async status element: ${taskId}`);
            pollAsyncTask(taskId, cacheKey, metricName);
        }
    });
});

//********** Darkmode Toggle *******
let darkmode = localStorage.getItem("darkmode");
//add a darkmode class to the body
const enableDarkmode = () => {
  document.body.classList.add("darkmode");
  localStorage.setItem("darkmode", "active");
};
//remove the darkmode class from the body
const disableDarkmode = () => {
    document.body.classList.remove('darkmode')
    localStorage.setItem('darkmode',null)
    
}
let datalogPopup;
document.addEventListener('DOMContentLoaded', (event) => {
    const themeSwitch = document.getElementById('theme-switch')
    //on document load check if darkmode is active
    if(darkmode === "active") enableDarkmode()
    //add a click event listener to the theme switch
    themeSwitch.addEventListener("click", () => {
        
        darkmode = localStorage.getItem('darkmode')
        
        darkmode !== "active" ? enableDarkmode() : disableDarkmode()
        toggleSlidesColor();

    })

    //data log handlers
    const dataLogButton = document.getElementById("datalog-button"); //navbar button

    const radioButtons = document.querySelectorAll('input[name="tableSwitch"]');
    const tableContainers = document.querySelectorAll(".scrollable-container");
    // popping up current log
    dataLogButton.addEventListener("click", () => {
        datalogPopup = document.getElementById("datalog-popup");
        const datalogContent = document.getElementById("datalog-content");

        //open popup
        datalogPopup.classList.add("open-popup");

        fetch("/view_logs")
            .then((response) => response.json())
            .then((data) => {
                const tbodyMaster = document.querySelector("#masterLogTable tbody");
                const tbodyFile = document.querySelector("#fileUploadLogTable");
                const tbodyMetric = document.querySelector("#metricLogTable");
                tbodyMaster.innerHTML = "";

                data.forEach((row) => {
                    const tr = document.createElement("tr");

                    ["timestamp", "logger", "message"].forEach((key) => {
                        const td = document.createElement("td");
                        td.textContent = row[key];
                        tr.appendChild(td);
                    });
                    tbodyMaster.appendChild(tr);

                    // row without logger
                    const trNoLogger = document.createElement("tr");
                    ["timestamp", "message"].forEach((key) => {
                        const td = document.createElement("td");
                        td.textContent = row[key];
                        trNoLogger.appendChild(td);
                    });

                    if (row.logger === "file_upload") {
                        tbodyFile.appendChild(trNoLogger);
                    } else if (row.logger === "metric") {
                        tbodyMetric.appendChild(trNoLogger);
                    }
                });
            })
            .catch((error) => {
                console.error("Error loading log:", error);
                openErrorPopup("Error loading log:", error);
            });
    });
    // switching between logs
    radioButtons.forEach((radio) => {
        radio.addEventListener("change", () => {
            tableContainers.forEach((container) =>
                container.classList.remove("active")
            );
            document.getElementById(radio.value).classList.add("active");
        });
    });
});
function closeDatalogPopup() {
    //close datalog popup has to be present in the DOM for the function to call already
    datalogPopup.classList.remove("open-popup");
}
function closeErrorPopup() {
    //error popup has to be present in the DOM for the function to call already
    errorPopup.classList.remove("open-popup");
}