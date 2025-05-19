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


function submitForm() {
    
    var form = document.getElementById('uploadForm');
    var formData = new FormData(form);

    // Get the values of the checkboxes and concatenate them with a comma
    var checkboxValues = Array.from(formData.getAll('checkboxValues')).join(',');
    var quasicheckboxValuesS = Array.from(formData.getAll('quasi identifiers to measure single attribute risk score')).join(',');
    var quasicheckboxValuesM = Array.from(formData.getAll('quasi identifiers to measure multiple attribute risk score')).join(',');
    var numFeaCheckboxValues = Array.from(formData.getAll('numerical features for feature relevancy')).join(',');
    var catFeaCheckboxValues = Array.from(formData.getAll('categorical features for feature relevancy')).join(',');
    
    // Add the concatenated checkbox values to the form data
    formData.set('correlation columns', checkboxValues);
    formData.set("quasi identifiers to measure single attribute risk score", quasicheckboxValuesS);
    formData.set("quasi identifiers to measure multiple attribute risk score", quasicheckboxValuesM);
    formData.set("numerical features for feature relevancy", numFeaCheckboxValues);
    formData.set("categorical features for feature relevancy", catFeaCheckboxValues);
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
            'Single attribute risk scoring', 'Multiple attribute risk scoring'
        ];
        visualizationTypes.forEach(function(type) {
            if (isKeyPresentAndDefined(data, type) && isKeyPresentAndDefined(data[type], type + ' Visualization')) {
                console.log('Adding visualization:', type);
                var image = data[type][type + ' Visualization'];
                var description = data[type]['Description'];
                var title = type;
                var jsonData = JSON.stringify(data);
                visualizationContent.push({ image: image, description: description, title: title, jsonData: jsonData});
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
              
                const imageBlobUrl = `data:image/jpeg;base64,${content.image}`;
                const visualizationId = `visualization_${index}`;
                metrics.innerHTML += `<div class="visualization-container">
                        <div class="toggle" onclick="toggleVisualization('${visualizationId}')">${content.title}</div>
                        <div id="${visualizationId}" style="display: none;">
                            <img src="${imageBlobUrl}" alt="Visualization ${index + 1} Chart">
                            <a href="${imageBlobUrl}" download="${content.title}.jpg" class="toggle  metric-download" style="padding:0px;"><svg xmlns="http://www.w3.org/2000/svg" height="24px" viewBox="0 -960 960 960" width="24px" fill="currentColor"><path d="M480-320 280-520l56-58 104 104v-326h80v326l104-104 56 58-200 200ZM240-160q-33 0-56.5-23.5T160-240v-120h80v120h480v-120h80v120q0 33-23.5 56.5T720-160H240Z"/></svg></a>

                            <div>${content.description}</div>
                            
                        </div>
                    
                    </div>`;
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
        //call popup
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
    //pn document lodad check if darkmode is active
    if(darkmode === "active") enableDarkmode()
    //add a click event listener to the theme switch
    themeSwitch.addEventListener("click", () => {
        
        darkmode = localStorage.getItem('darkmode')
        darkmode !== "active" ? enableDarkmode() : disableDarkmode()
    }) 
});