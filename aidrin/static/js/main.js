function togglePillarDropdown(id) {
    const container = document.getElementById(id); //
    const subElements = container.querySelectorAll('.toggle-button');

    const header = document.querySelector(`h3[onclick*="${id}"]`);
    const svg = header.querySelector("svg"); 
    subElements.forEach(element => {
        if (element.style.display === 'none' || element.style.display === '') {
            element.style.display = 'flex';
            svg.innerHTML = '<path d="M480-360 280-559.33h400L480-360Z"/>';
            
        } else {
            element.style.display = 'none';
            svg.innerHTML = '<path d="M400-280v-400l200 200-200 200Z"/>';
        }
    });
}


//for uploads
function uploadForm() {
    const form = document.getElementById('uploadForm');
    form.submit();  // Submit the form automatically when a file is selected
}
//to clear
function clearFile() {
    fetch('/clear', {
        method: 'POST',
    })
    .then(response => {
        if (response.redirected) {
            // Redirect to the specified location
            window.location.href = response.url;
        }
    })
    .catch(error => {
        console.error('Error:', error);
        openErrorPopup("File Clear", error); // call error popup
    });
}
//get file type from user
document.addEventListener("DOMContentLoaded", function () {
    //file type selector and file input field
    const fileTypeElement = document.getElementById("fileTypeSelector");
    const fileInput = document.getElementById("file");
    const fileUploadMessage = document.getElementById("FileUploadMessage");
    // Bind select to function
    fileTypeElement.addEventListener("change", function () {
        updateFileInputBasedOnType(fileTypeElement, fileInput, fileUploadMessage);
    });
    // Call it once on page load 
    updateFileInputBasedOnType(fileTypeElement, fileInput,fileUploadMessage);
});
//changes file upload ability
function updateFileInputBasedOnType(fileTypeElement, fileInput, fileUploadMessage) {
    const fileType = fileTypeElement.value;
    //if a filetype is present, set to that filetype only, otherwise disable
    if (fileType) {
        fileInput.disabled = false;
        fileInput.setAttribute("accept", fileType);
        console.log("USER SELECTED FILETYPE: " + fileType);
        fileUploadMessage.style.opacity="1";
    } else {
        fileInput.disabled = true;
        fileInput.removeAttribute("accept");
        fileUploadMessage.style.opacity="0";
        console.log("FILE UPLOAD DISABLED");
    }
}


function submitForm() {
    
    var form = document.getElementById('uploadForm');
    var formData = new FormData(form);

    // Get the values of the checkboxes and concatenate them with a comma
    var checkboxValues = Array.from(formData.getAll('checkboxValues')).join(',');
    var numFeaCheckboxValues = Array.from(formData.getAll('numerical features for feature relevancy')).join(',');
    var catFeaCheckboxValues = Array.from(formData.getAll('categorical features for feature relevancy')).join(',');
    
    // Add the concatenated checkbox values to the form data
    formData.set('correlation columns', checkboxValues);
    formData.set("numerical features for feature relevancy", numFeaCheckboxValues);
    formData.set("categorical features for feature relevancy", catFeaCheckboxValues);
    
    // Note: We don't need to modify the quasi-identifier fields as they should remain as lists
    // The backend will handle both string and list formats
    // Populate metrics visualizations
    var metrics = document.getElementById("metrics");
    if(metrics){
        metrics.innerHTML = '<p>Loading visualizations, please wait...</p>';
    } else{
        console.error("No Element ID");
        console.log("No Element ID");
        print("No Element ID");
    }
    const url = new URL(window.location.href);
    url.searchParams.set('returnType', 'json');
    const currentURL = url.toString();
    fetch(currentURL, {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (response.ok && response.headers.get('content-type')?.includes('application/json')) {
            return response.json();
        } else {
            throw new Error('Server did not return valid JSON.');
        }
    })
    .then(data => {
        
        if (data.trigger === "correlationError") {
            openErrorPopup("Invalid Request","Input Feature and Target Feature cannot be the same"); // call error popup
        } 
        console.log('Server Response:', data);
        var resultContainer = document.getElementById('resultContainer');

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
        visualizationTypes.forEach(function(type) {
            console.log('Checking type:', type);
            console.log('Data keys:', Object.keys(data));
            if (isKeyPresentAndDefined(data, type)) {
                console.log('Found type in data:', type);
                console.log('Type data keys:', Object.keys(data[type]));
                
                // Check if this is an async task
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
                    console.log('Starting polling for task:', data[type]['task_id']);
                    pollAsyncTask(data[type]['task_id'], data[type]['cache_key'], type);
                    
                } else if (isKeyPresentAndDefined(data[type], type + ' Visualization')) {
                    console.log('Adding visualization:', type);
                    var image = data[type][type + ' Visualization'];
                    var value = data[type]['Value'] || 'N/A'; 
                    var description = data[type]['Description'] || '';
                    var interpretation = data[type]['Graph interpretation'] || '';
                    var riskScore = data[type]['Risk Score'] || 'N/A'; 
                    var riskLevel = data[type]['Risk Level'] || null;
                    var riskColor = data[type]['Risk Color'] || null;
                    var title = type;
                    var jsonData = JSON.stringify(data);
                    
                    // Check if there's an error or if the image is empty
                    if (data[type]['Error']) {
                        console.log('Error in', type, ':', data[type]['Error']);
                        // Still add to visualization content but with error message
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
                            hasError: true
                        });
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
            
            // Add each visualization to the metric visualization section
            visualizationContent.forEach(function(content, index) {
                //check if vizualization is duplicity with score=0 (no dublicates)
              
                const visualizationId = `visualization_${index}`;
                let visualizationHtml = `<div class="visualization-container">
                        <div class="toggle" onclick="toggleVisualization('${visualizationId}')">${content.title}</div>
                        <div id="${visualizationId}" style="display: none;">`;
                
                if (content.hasError) {
                    // Display error message instead of image
                    visualizationHtml += `<div style="text-align: center; padding: 20px; color: #d32f2f;">
                        <strong>Error:</strong> ${content.description}
                    </div>`;
                } else if (content.isAsync) {
                    // Display async task status with progress bar
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
                        
                        <div style="font-size: 12px; color: #888;">
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
                } else if (content.image && content.image.trim() !== "") {
                    // Display normal visualization
                    const imageBlobUrl = `data:image/jpeg;base64,${content.image}`;
                    visualizationHtml += `<img src="${imageBlobUrl}" alt="Visualization ${index + 1} Chart">
                    <a href="${imageBlobUrl}" download="${content.title}.jpg" class="toggle  metric-download" style="padding:0px;"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="currentColor"><path d="M480-320 280-520l56-58 104 104v-326h80v326l104-104 56 58-200 200ZM240-160q-33 0-56.5-23.5T160-240v-120h80v120h480v-120h80v120q0 33-23.5 56.5T720-160H240Z"/></svg></a>`;
                } else {
                    // Display message for empty visualization
                    visualizationHtml += `<div style="text-align: center; padding: 20px; color: #666;">
                        No visualization available for this metric.
                    </div>`;
                }
                
                visualizationHtml += `
                            ${content.riskScore !== 'N/A' ? `<div><strong>Risk Score:</strong> ${content.riskScore}</div>` : ''}
                    ${content.riskLevel ? `<div><strong>Risk Level:</strong> <span style="color: ${content.riskColor}; font-weight: bold;">${content.riskLevel}</span></div>` : ''}
                            ${content.value !== 'N/A' ? `<div><strong>${content.title}:</strong> ${content.value}</div>` : ''}
                    ${content.description ? `<div><strong>Description:</strong> ${content.description}</div>` : ''}
                    ${content.interpretation && content.title !== 'Class Imbalance' ? `<div><strong>Graph interpretation:</strong> ${content.interpretation} ${getDocsButton(content.title)}</div>` : ''}
                `;
                
                // Special handling for Class Imbalance: show Imbalance Degree Value
                if (content.title === 'Class Imbalance' && data['Class Imbalance'] && data['Class Imbalance']['Imbalance degree']) {
                    const imbalanceData = data['Class Imbalance']['Imbalance degree'];
                    if (imbalanceData['Imbalance Degree score'] !== undefined) {
                        const score = imbalanceData['Imbalance Degree score'];
                        // Get the distance metric from the form data for reference
                        const distanceMetric = getDistanceMetricName();
                    visualizationHtml += `<div><strong>Imbalance Degree:</strong> ${score}</div>`;
                        // Add graph interpretation below Imbalance Degree
                        if (content.interpretation) {
                            visualizationHtml += `<div><strong>Graph interpretation:</strong> ${content.interpretation} <a href="/class-imbalance-docs" target="_blank" style="margin-left:10px; color:#4a90e2; font-style:italic;">See documentation</a></div>`;
                        }
                        setTimeout(() => { if (typeof showImbalanceDegreeDocsBtn === 'function') showImbalanceDegreeDocsBtn(); }, 0);
                    } else if (imbalanceData['Error'] !== undefined) {
                        const error = imbalanceData['Error'];
                        const distanceMetric = getDistanceMetricName();
                        visualizationHtml += `<div><strong>Imbalance Degree:</strong> <span style="color: red;">${error}</span></div>`;
                    }
                }
                
                // Special handling for Privacy Metrics: show specific values
                if (content.title === 'k-Anonymity' && data['k-Anonymity']) {
                    const kData = data['k-Anonymity'];
                    if (kData['k-Value'] !== undefined) {
                        visualizationHtml += `<div><strong>k-Value:</strong> ${kData['k-Value']}</div>`;
                    }
                }
                
                if (content.title === 'l-Diversity' && data['l-Diversity']) {
                    const lData = data['l-Diversity'];
                    if (lData['l-Value'] !== undefined) {
                        visualizationHtml += `<div><strong>l-Value:</strong> ${lData['l-Value']}</div>`;
                    }
                }
                
                if (content.title === 't-Closeness' && data['t-Closeness']) {
                    const tData = data['t-Closeness'];
                    if (tData['t-Value'] !== undefined) {
                        visualizationHtml += `<div><strong>t-Value:</strong> ${tData['t-Value']}</div>`;
                    }
                }
                
                if (content.title === 'Entropy Risk' && data['Entropy Risk']) {
                    const entropyData = data['Entropy Risk'];
                    if (entropyData['Entropy-Value'] !== undefined) {
                        visualizationHtml += `<div><strong>Entropy Value:</strong> ${entropyData['Entropy-Value']}</div>`;
                    }
                }
                
                visualizationHtml += `
                        </div>
                    </div>`;
                
                metrics.innerHTML += visualizationHtml;
            });
            
            //check if duplicity is present and 0 (no duplicity)
            if (isKeyPresentAndDefined(data, 'Duplicity') && isKeyPresentAndDefined(data['Duplicity'], 'Duplicity scores') && data['Duplicity']['Duplicity scores']['Overall duplicity of the dataset'] === 0) {
                metrics.innerHTML += `<div class="visualization-container">
                    <div class="toggle" onclick="toggleVisualization('duplicity')">Duplicity</div>
                    <div id="duplicity" style="display: none; text-align: center;">
                        No duplicates found 
                    </div>      
                </div>`;
            }

            
            
            // Assuming 'data' is your dictionary
            const modifiedData = removeVisualizationKey(data);
            const jsonBlobUrl = `data:application/json,${encodeURIComponent(JSON.stringify(modifiedData))}`;
            // Add the "Download JSON" link for the last jsonData outside the loop
            metrics.innerHTML += `<a href="${jsonBlobUrl}" download="report.json" class="toggle">Download JSON Report</a>`;
           

            
        } else {
            //check if duplicity is present and 0 (no duplicity)
            if (isKeyPresentAndDefined(data, 'Duplicity') && isKeyPresentAndDefined(data['Duplicity'], 'Duplicity scores') && data['Duplicity']['Duplicity scores']['Overall duplicity of the dataset'] === 0) {
                metrics.innerHTML = `<div class="heading">Readiness Report</div>`;
                metrics.innerHTML += `<div class="visualization-container">
                    <div class="toggle" onclick="toggleVisualization('duplicity')">Duplicity</div>
                    <div id="duplicity" style="display: none; text-align: center;">
                        No duplicates found 
                    </div>      
                </div>`;
            } else{
            metrics.innerHTML='<h3 style="text-align:center;">No visualizations available.</h3>';
            }
            // Assuming 'data' is your dictionary
            const modifiedData = removeVisualizationKey(data);
            const jsonBlobUrl = `data:application/json,${encodeURIComponent(JSON.stringify(modifiedData))}`;
            // Add the "Download JSON" link for the last jsonData outside the loop
            metrics.innerHTML+=`<a href="${jsonBlobUrl}" download="report.json" class="toggle">Download JSON Report</a>`;
            
        }
    })
    .catch(error => {
        console.error('Error:', error);
        openErrorPopup("Visualization Error",error); // call error popup
        
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
    .catch(error => {
        console.error('Error:', error);
        openErrorPopup("", error); // call error popup
    });
}

function removeVisualizationKey(data) {
    for (let key in data) {
        if (typeof data[key] === 'object' && data[key] !== null) {
            // If the value is an object, recursively call removeVisualizationKey
            data[key] = removeVisualizationKey(data[key]);
        } else if (key.endsWith(' Visualization')) {
            // If the key is 'Completeness Visualization', remove it
            delete data[key];
        }
    }
    return data;
}

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

function downloadJSON() {
    // Get the JSON data
    var jsonData = JSON.stringify(resp_data, null, 2);

    // Create a Blob with the JSON data
    var blob = new Blob([jsonData], { type: 'application/json' });

    // Create a link element
    var link = document.createElement('a');

    // Set the link's href attribute to a data URL containing the Blob
    link.href = window.URL.createObjectURL(blob);

    // Set the link's download attribute to specify the file name
    link.download = 'result.json';

    // Append the link to the document
    document.body.appendChild(link);

    // Trigger a click on the link to start the download
    link.click();

    // Remove the link from the document
    document.body.removeChild(link);
}

function showResults() {
    // Show Completeness Visualization content if it exists
    var duplicityScoreResult = document.getElementById('duplicityScoreResult');
    if (duplicityScoreResult) {
        duplicityScoreResult.style.display = 'block';
    }
    var imbalanceScoreResult = document.getElementById('imbalanceScoreResult');
    if (imbalanceScoreResult) {
        imbalanceScoreResult.style.display = 'block';
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
    console.log("Checkbox value:", checkbox.value); // For debugging
}
// Ensure proper initial state on page load
document.addEventListener("DOMContentLoaded", function() {
    // Get all checkboxes inside each checkboxContainer
    document.querySelectorAll(".checkboxContainer").forEach(container => {
        
        // For each container, get the checkbox inside and set the initial state
        
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
});

//********** Darkmode Toggle *******
let darkmode = localStorage.getItem('darkmode')
//add a darkmode class to the body
const enableDarkmode = () => {
    document.body.classList.add('darkmode')
    localStorage.setItem('darkmode','active')
    
}
//remove the darkmode class from the body
const disableDarkmode = () => {
    document.body.classList.remove('darkmode')
    localStorage.setItem('darkmode',null)
    
}
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
});

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
    console.log(`Starting polling for ${metricName} task: ${taskId} (max ${maxAttempts} attempts, ${interval}ms intervals)`);
    
    function checkTask() {
        attempts++;
        
        console.log(`Polling attempt ${attempts}/${maxAttempts} for ${metricName}`);
        
        fetch(`/check_and_update_task/${taskId}/${encodeURIComponent(cacheKey)}`)
            .then(response => {
                console.log(`📡 Poll response status: ${response.status} for ${metricName}`);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                console.log(`Poll response data for ${metricName}:`, data);
                
                // Get DOM elements for progress bar and status
                const progressBar = document.querySelector(`#task-status-${taskId}`).closest('.async-task-status').querySelector('.progress-bar');
                const statusSpan = document.querySelector(`#task-status-${taskId}`);
                
                // Update progress bar and status from real Celery data
                if (data.state === 'PROGRESS' && data.info) {
                    // Use real progress from Celery
                    const realProgress = data.info.current || 0;
                    const realStatus = data.info.status || 'Processing...';
                    
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
                    
                    console.log(`Real progress update: ${realProgress}% - ${realStatus}`);
                } else {
                    // Fallback for pending tasks without progress info
                    if (statusSpan) {
                        const timeElapsed = Math.round((attempts * interval) / 1000);
                        statusSpan.textContent = `Processing... (${timeElapsed}s elapsed)`;
                    }
                }
                
                if (data.completed) {
                    if (data.success) {
                        // Task completed successfully, complete the progress bar
                        if (progressBar) {
                            progressBar.style.width = '100%';
                            progressBar.style.background = 'linear-gradient(90deg, #4CAF50, #8BC34A)';
                        }
                        if (statusSpan) {
                            statusSpan.textContent = 'Calculation completed!';
                        }
                        
                        console.log(`${metricName} calculation completed successfully`);
                        
                        // Wait a moment to show completion, then update with results
                        setTimeout(() => {
                            updateAsyncTaskWithResults(taskId, metricName, data.result);
                        }, 1000);
                    } else {
                        // Task failed
                        if (progressBar) {
                            progressBar.style.background = 'linear-gradient(90deg, #F44336, #E57373)';
                        }
                        if (statusSpan) {
                            statusSpan.textContent = 'Calculation failed';
                        }
                        console.error(`${metricName} calculation failed:`, data.error);
                        updateTaskStatus(taskId, metricName, 'FAILED', data.error || 'Task failed');
                    }
                } else {
                    // Task still running, continue polling
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
                        updateTaskStatus(taskId, metricName, 'TIMEOUT', 'Polling timeout reached. The task may still be running in the background.');
                    }
                }
            })
            .catch(error => {
                console.error(`🚨 Error polling ${metricName} task:`, error);
                
                if (attempts < maxAttempts) {
                    // Retry on error
                    setTimeout(checkTask, interval);
                } else {
                    // Max retries reached
                    if (progressBar) {
                        progressBar.style.background = 'linear-gradient(90deg, #F44336, #E57373)';
                    }
                    if (statusSpan) {
                        statusSpan.textContent = 'Connection error';
                    }
                    updateTaskStatus(taskId, metricName, 'ERROR', error.message);
                }
            });
    }
    
    // Start polling
    checkTask();
}

function updateAsyncTaskWithResults(taskId, metricName, results) {
    console.log(`updateAsyncTaskWithResults called:`, { taskId, metricName, results });
    
    // Find the async task placeholder
    const asyncElement = document.querySelector(`[data-task-id="${taskId}"]`);
    console.log(`Found asyncElement:`, asyncElement);
    
    if (asyncElement) {
        // Find the parent visualization container
        const visualizationContainer = asyncElement.closest('.visualization-container');
        console.log(`Found visualizationContainer:`, visualizationContainer);
        
        const visualizationId = visualizationContainer ? visualizationContainer.querySelector('.toggle').getAttribute('onclick').match(/'([^']+)'/)[1] : null;
        console.log(`Extracted visualizationId:`, visualizationId);
        
        if (visualizationId) {
            const contentDiv = document.getElementById(visualizationId);
            console.log(`Found contentDiv:`, contentDiv);
            
            if (contentDiv && results) {
                // Build the completed visualization HTML
                let completedHtml = '';
                
                console.log(`Building HTML for results:`, Object.keys(results));
                
                // Check if there's an error
                if (results['Error']) {
                    console.log(`Error in results:`, results['Error']);
                    completedHtml = `<div style="text-align: center; padding: 20px; color: #d32f2f;">
                        <strong>Error:</strong> ${results['Error']}
                    </div>`;
                } else {
                    // Add visualization image if present
                    const vizKey = `${metricName} Visualization`;
                    console.log(`Looking for visualization key:`, vizKey);
                    console.log(`Available keys:`, Object.keys(results));
                    console.log(`Visualization data length:`, results[vizKey] ? results[vizKey].length : 'Not found');
                    
                    if (results[vizKey] && results[vizKey].trim() !== "") {
                        console.log(`Adding visualization image for ${metricName}`);
                        const imageBlobUrl = `data:image/jpeg;base64,${results[vizKey]}`;
                        completedHtml += `<img src="${imageBlobUrl}" alt="${metricName} Chart" style="max-width: 100%; height: auto;">
                        <a href="${imageBlobUrl}" download="${metricName}.jpg" class="toggle metric-download" style="padding:0px;">
                            <svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="currentColor">
                                <path d="M480-320 280-520l56-58 104 104v-326h80v326l104-104 56 58-200 200ZM240-160q-33 0-56.5-23.5T160-240v-120h80v120h480v-120h80v120q0 33-23.5 56.5T720-160H240Z"/>
                            </svg>
                        </a>`;
                    } else {
                        console.log(`No visualization found for key: ${vizKey}`);
                    }
                }
                
                // Add risk score if present
                if (results['Risk Score'] && results['Risk Score'] !== 'N/A') {
                    completedHtml += `<div><strong>Risk Score:</strong> ${results['Risk Score']}</div>`;
                }
                
                // Add risk level if present
                if (results['Risk Level']) {
                    const riskColor = results['Risk Color'] || '#000';
                    completedHtml += `<div><strong>Risk Level:</strong> <span style="color: ${riskColor}; font-weight: bold;">${results['Risk Level']}</span></div>`;
                }
                
                // Add dataset risk score for multiple attribute
                if (results['Dataset Risk Score']) {
                    completedHtml += `<div><strong>Dataset Risk Score:</strong> ${results['Dataset Risk Score']}</div>`;
                }
                
                // Add description if present
                if (results['Description']) {
                    completedHtml += `<div><strong>Description:</strong> ${results['Description']}</div>`;
                }
                
                // Add graph interpretation if present
                if (results['Graph interpretation']) {
                    completedHtml += `<div><strong>Graph interpretation:</strong> ${results['Graph interpretation']} ${getDocsButton(metricName)}</div>`;
                }
                
                // Replace the async placeholder with the completed results
                contentDiv.innerHTML = completedHtml;
                
                console.log(`Successfully updated ${metricName} with completed results`);
                console.log(`Final HTML length:`, completedHtml.length);
            } else {
                console.error(`Could not find contentDiv or results missing:`, { contentDiv, results });
            }
        } else {
            console.error(`Could not extract visualizationId from container`);
        }
    } else {
        console.error(`Could not find async element for task ${taskId}`);
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

// Auto-start polling for async tasks when page loads
document.addEventListener('DOMContentLoaded', function() {
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
            console.log(`Starting polling for ${metricName} task: ${taskId}`);
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
    
    // Check for task IDs in the page content (fallback)
    const pageContent = document.body.innerHTML;
    const taskIdMatches = pageContent.match(/"task_id":\s*"([^"]+)"/g);
    
    if (taskIdMatches) {
        console.log('Found task IDs in page content:', taskIdMatches);
        // This is a more complex case that would need additional parsing
    }
});