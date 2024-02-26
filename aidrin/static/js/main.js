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
    formData.set("quasi identifiers to measure single attribute risk score",quasicheckboxValuesS)
    formData.set("quasi identifiers to measure multiple attribute risk score",quasicheckboxValuesM)
    formData.set("numerical features for feature relevancy",numFeaCheckboxValues)
    formData.set("categorical features for feature relevancy",catFeaCheckboxValues)

    for (var pair of formData.entries()) {
        console.log(pair[0] + ': ' + pair[1]);
    }

    fetch('/upload_file', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        var resultContainer = document.getElementById('resultContainer');

        resp_data = data;

        // Function to check if a key is present and not undefined
        function isKeyPresentAndDefined(obj, key) {
            return obj && obj[key] !== undefined;
        }
        
        // Check if "Completeness Visualization" key is present
        if (isKeyPresentAndDefined(data, 'Completeness') && isKeyPresentAndDefined(data['Completeness'], 'Completeness Visualization')) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="complVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Completeness']['Completeness Visualization'] + '" alt="Completeness Chart">' +
                '<div style="margin-left: 10px;">' +data['Completeness']['Description'] + '</div>' +
                '</div>';
        }

        // Check if "Outliers Visualization" key is present
        if (isKeyPresentAndDefined(data, 'Outliers') && isKeyPresentAndDefined(data['Outliers'], 'Outliers Visualization')) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="outVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Outliers']['Outliers Visualization'] + '" alt="Outliers Chart">' +
                '<div style="margin-left: 10px;">' +data['Outliers']['Description'] + '</div>' +
                '</div>';
        }

        if (
            isKeyPresentAndDefined(data, 'Representation Rate') &&
            isKeyPresentAndDefined(data['Representation Rate'], 'Representation Rate Chart')
        ) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="repVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Representation Rate']['Representation Rate Chart']+ '" alt="Representation Rate Chart">' +
                '<div style="margin-left: 10px;">' +data['Representation Rate']['Description'] + '</div>' +
                '</div>';
        }

        if (isKeyPresentAndDefined(data, 'Statistical Rate') && isKeyPresentAndDefined(data['Statistical Rate'], 'class_proportions_plot')) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="statRateVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Statistical Rate']['class_proportions_plot'] + '" alt="Statistical rate bar plot">' +
                '<div style="margin-left: 10px;">' +data['Statistical Rate']['Description'] + '</div>' +
                '</div>';
        }

        // Check if "Representation Rate Comparison with Real World" key and "Comparisons" key are present
        if (
            isKeyPresentAndDefined(data, 'Representation Rate Comparison with Real World') &&
            isKeyPresentAndDefined(data['Representation Rate Comparison with Real World']['Comparisons'], 'Comparison Visualization')
        ) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="compVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Representation Rate Comparison with Real World']['Comparisons']['Comparison Visualization'] + '" alt="Comparisons Chart">' +
                '<div style="margin-left: 10px;">' +data['Representation Rate Comparison with Real World']['Description'] + '</div>' +
                '</div>';
        }

        if (isKeyPresentAndDefined(data, 'Correlations Analysis') && isKeyPresentAndDefined(data['Correlations Analysis'], 'Categorical-Categorical Correlation Matrix')) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="catCorrVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Correlations Analysis']['Categorical-Categorical Correlation Matrix'] + '" alt="Categorical-Categorical Correlation Matrix">' +
                '<div style="margin-left: 10px;">' +data['Correlations Analysis']['Description'] + '</div>' +
                '</div>';
            
        }

        if (isKeyPresentAndDefined(data, 'Correlations Analysis') && isKeyPresentAndDefined(data['Correlations Analysis'], 'Numerical-Numerical Correlation Matrix')) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="numCorrVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Correlations Analysis']['Numerical-Numerical Correlation Matrix'] + '" alt="Numerical-Numerical Correlation Matrix">' +
                '<div style="margin-left: 10px;">' +data['Correlations Analysis']['Description'] + '</div>' +
                '</div>';
            
        }

        if (isKeyPresentAndDefined(data, 'Feature relevance') && isKeyPresentAndDefined(data['Feature relevance'], 'summary plot')) {                    
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="featureRelVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Feature relevance']['summary plot'] + '" alt="Shapley value plot">' +
                '<div style="margin-left: 10px;">' +data['Feature relevance']['Description'] + '</div>' +
                '</div>';
        }
        if (isKeyPresentAndDefined(data, 'Class imbalance') && isKeyPresentAndDefined(data['Class imbalance'], 'Class distribution plot')) {                    
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="classDisVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Class imbalance']['Class distribution plot'] + '" alt="Class distribution plot">' +
                '<div style="margin-left: 10px;">' +data['Class imbalance']['Description'] + '</div>' +
                '</div>';
        }
        
        if (isKeyPresentAndDefined(data, 'DP statistics') && isKeyPresentAndDefined(data['DP statistics'], 'Combined Plots')) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="noisyVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['DP statistics']['Combined Plots'] + '" alt="Normal vs Noisy Feature Box Plots">' +
                '<div style="margin-left: 10px;">' +data['DP statistics']['Description'] + '</div>' +
                '</div>';
        }

        if (isKeyPresentAndDefined(data, 'Single attribute risk scoring') && isKeyPresentAndDefined(data['Single attribute risk scoring'], 'BoxPlot')) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="singleRiskVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Single attribute risk scoring']['BoxPlot'] + '" alt="Single attribute risk score box plots">'+
                '<div style="margin-left: 10px;">' +data['Single attribute risk scoring']['Description'] + '</div>' +
                '</div>' 
                
        }
        if (isKeyPresentAndDefined(data, 'Multiple attribute risk scoring') && isKeyPresentAndDefined(data['Multiple attribute risk scoring'], 'Box Plot')) {
            // Display the chart image and description in a single div
            resultContainer.innerHTML += '<div id="multipleRiskVis" style="display:none; text-align: left;">' +
                '<img style="margin-right: 10px;" src="data:image/png;base64,' + data['Multiple attribute risk scoring']['Box Plot'] + '" alt="Multiple attribute risk score box plots">'+
                '<div style="margin-left: 10px;">' +data['Multiple attribute risk scoring']['Description'] + '</div>' +
                '</div>' 
                
        }
        
        
        

        //Display other result information as JSON
        if (data['Duplicity'] && data['Duplicity']['Duplicity scores'] && data['Duplicity']['Duplicity scores']['Overall duplicity of the dataset'] !== undefined) {
            resultContainer.innerHTML += '<div id="duplicityScoreResult" style="display:none"> <h3> Duplicity Scores </h3>'+ 
                '<pre> Overall Duplicity: ' + data['Duplicity']['Duplicity scores']['Overall duplicity of the dataset'] + '</pre>' +
                '</div>';
        }

        if (data['Class imbalance'] && data['Class imbalance']['Imbalance degree'] && data['Class imbalance']['Imbalance degree']['Imbalance degree score'] !== undefined) {
            resultContainer.innerHTML += '<div id="imbalanceScoreResult" style="display:none"> <h3> Class Imbalance Scores </h3>'+ 
                '<pre> Imbalance degree: ' + data['Class imbalance']['Imbalance degree']['Imbalance degree score'] + '</pre>' +
                '</div>';
        }

        // resultContainer.innerHTML += '<pre id="scoreResult" style="display:none;">' + data['Duplicity']['Duplicity scores']['Overall duplicity of the dataset'] + '</pre>';
        
        // Show the result container after the response is generated
        resultContainer.style.display = 'block';

        // Show the buttons after the response is generated
        document.getElementById('buttonsContainer').style.display = 'block';

        
    })
    .catch(error => {
        console.error('Error:', error);
    });
}

function showVisualization() {
    // Show Completeness Visualization content if it exists
    var completenessContent = document.getElementById('complVis');

    if (completenessContent) {
        completenessContent.style.display = 'flex';
        completenessContent.style.alignItems = 'center';
        completenessContent.style.border = '1px solid #ddd'; // Add a border
        completenessContent.style.borderRadius = '8px'; // Add rounded corners
        completenessContent.style.padding = '10px'; // Add some padding
        completenessContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        completenessContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        completenessContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        completenessContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        completenessContent.querySelector('div').style.color = '#333'; // Set text color
        completenessContent.querySelector('div').style.fontSize = '20px'; // Set font size
        completenessContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    // Show Outliers Visualization content if it exists
    var outliersContent = document.getElementById('outVis');
    if (outliersContent) {
        outliersContent.style.display = 'flex';
        outliersContent.style.alignItems = 'center';
        outliersContent.style.border = '1px solid #ddd'; // Add a border
        outliersContent.style.borderRadius = '8px'; // Add rounded corners
        outliersContent.style.padding = '10px'; // Add some padding
        outliersContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        outliersContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        outliersContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        outliersContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        outliersContent.querySelector('div').style.color = '#333'; // Set text color
        outliersContent.querySelector('div').style.fontSize = '20px'; // Set font size
        outliersContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    // Show Representation Rate Visualization content if it exists
    var representationRateContent = document.getElementById('repVis');
    if (representationRateContent) {
        representationRateContent.style.display = 'flex';
        representationRateContent.style.alignItems = 'center';
        representationRateContent.style.border = '1px solid #ddd'; // Add a border
        representationRateContent.style.borderRadius = '8px'; // Add rounded corners
        representationRateContent.style.padding = '10px'; // Add some padding
        representationRateContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        representationRateContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        representationRateContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        representationRateContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        representationRateContent.querySelector('div').style.color = '#333'; // Set text color
        representationRateContent.querySelector('div').style.fontSize = '20px'; // Set font size
        representationRateContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    // Show Comparison Visualization content if it exists
    var comparisonContent = document.getElementById('compVis');
    if (comparisonContent) {
        comparisonContent.style.display = 'flex';
        comparisonContent.style.alignItems = 'center';
        comparisonContent.style.border = '1px solid #ddd'; // Add a border
        comparisonContent.style.borderRadius = '8px'; // Add rounded corners
        comparisonContent.style.padding = '10px'; // Add some padding
        comparisonContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        comparisonContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        comparisonContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        comparisonContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        comparisonContent.querySelector('div').style.color = '#333'; // Set text color
        comparisonContent.querySelector('div').style.fontSize = '20px'; // Set font size
        comparisonContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    // Statistical Rate Visualization content if it exists
    var stateRateVis = document.getElementById('statRateVis');
    if (stateRateVis) {
        stateRateVis.style.display = 'flex';
        stateRateVis.style.alignItems = 'center';
        stateRateVis.style.border = '1px solid #ddd'; // Add a border
        stateRateVis.style.borderRadius = '8px'; // Add rounded corners
        stateRateVis.style.padding = '10px'; // Add some padding
        stateRateVis.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        stateRateVis.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        stateRateVis.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        stateRateVis.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        stateRateVis.querySelector('div').style.color = '#333'; // Set text color
        stateRateVis.querySelector('div').style.fontSize = '20px'; // Set font size
        stateRateVis.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }
    // Show Correlation Visualization content if it exists
    var catCorrContent = document.getElementById('catCorrVis');
    if (catCorrContent) {
        catCorrContent.style.display = 'flex';
        catCorrContent.style.alignItems = 'center';
        catCorrContent.style.border = '1px solid #ddd'; // Add a border
        catCorrContent.style.borderRadius = '8px'; // Add rounded corners
        catCorrContent.style.padding = '10px'; // Add some padding
        catCorrContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        catCorrContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        catCorrContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        catCorrContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        catCorrContent.querySelector('div').style.color = '#333'; // Set text color
        catCorrContent.querySelector('div').style.fontSize = '20px'; // Set font size
        catCorrContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    var numCorrContent = document.getElementById('numCorrVis');
    if (numCorrContent) {
        numCorrContent.style.display = 'flex';
        numCorrContent.style.alignItems = 'center';
        numCorrContent.style.border = '1px solid #ddd'; // Add a border
        numCorrContent.style.borderRadius = '8px'; // Add rounded corners
        numCorrContent.style.padding = '10px'; // Add some padding
        numCorrContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        numCorrContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        numCorrContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        numCorrContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        numCorrContent.querySelector('div').style.color = '#333'; // Set text color
        numCorrContent.querySelector('div').style.fontSize = '20px'; // Set font size
        numCorrContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    
    var featureRelContent = document.getElementById('featureRelVis');
    if (featureRelContent) {
        featureRelContent.style.display = 'flex';
        featureRelContent.style.alignItems = 'center';
        featureRelContent.style.border = '1px solid #ddd'; // Add a border
        featureRelContent.style.borderRadius = '8px'; // Add rounded corners
        featureRelContent.style.padding = '10px'; // Add some padding
        featureRelContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        featureRelContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        featureRelContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        featureRelContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        featureRelContent.querySelector('div').style.color = '#333'; // Set text color
        featureRelContent.querySelector('div').style.fontSize = '20px'; // Set font size
        featureRelContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    var classImbalanceContent = document.getElementById('classDisVis');
    if (classImbalanceContent) {
        classImbalanceContent.style.display = 'flex';
        classImbalanceContent.style.alignItems = 'center';
        classImbalanceContent.style.border = '1px solid #ddd'; // Add a border
        classImbalanceContent.style.borderRadius = '8px'; // Add rounded corners
        classImbalanceContent.style.padding = '10px'; // Add some padding
        classImbalanceContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        classImbalanceContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        classImbalanceContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        classImbalanceContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        classImbalanceContent.querySelector('div').style.color = '#333'; // Set text color
        classImbalanceContent.querySelector('div').style.fontSize = '20px'; // Set font size
        classImbalanceContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    // Show Normal vs Noisy Feature Visualization content if it exists
    var noisyContent = document.getElementById('noisyVis');
    if (noisyContent) {
        noisyContent.style.display = 'flex';
        noisyContent.style.alignItems = 'center';
        noisyContent.style.border = '1px solid #ddd'; // Add a border
        noisyContent.style.borderRadius = '8px'; // Add rounded corners
        noisyContent.style.padding = '10px'; // Add some padding
        noisyContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        noisyContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        noisyContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        noisyContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        noisyContent.querySelector('div').style.color = '#333'; // Set text color
        noisyContent.querySelector('div').style.fontSize = '20px'; // Set font size
        noisyContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

     // Show single attribute risk scores
     var singleRiskContent = document.getElementById('singleRiskVis');
    if (singleRiskContent) {
        singleRiskContent.style.display = 'flex';
        singleRiskContent.style.alignItems = 'center';
        singleRiskContent.style.border = '1px solid #ddd'; // Add a border
        singleRiskContent.style.borderRadius = '8px'; // Add rounded corners
        singleRiskContent.style.padding = '10px'; // Add some padding
        singleRiskContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        singleRiskContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        singleRiskContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        singleRiskContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        singleRiskContent.querySelector('div').style.color = '#333'; // Set text color
        singleRiskContent.querySelector('div').style.fontSize = '20px'; // Set font size
        singleRiskContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    // Show multiple attribute risk scores
    var multipleRiskContent = document.getElementById('multipleRiskVis');
    if (multipleRiskContent) {
        multipleRiskContent.style.display = 'flex';
        multipleRiskContent.style.alignItems = 'center';
        multipleRiskContent.style.border = '1px solid #ddd'; // Add a border
        multipleRiskContent.style.borderRadius = '8px'; // Add rounded corners
        multipleRiskContent.style.padding = '10px'; // Add some padding
        multipleRiskContent.style.boxShadow = '0 4px 8px rgba(0, 0, 0, 0.1)'; // Add a subtle box shadow

        // Styles for the image
        multipleRiskContent.querySelector('img').style.maxWidth = '100%'; // Make sure the image doesn't exceed the container width
        multipleRiskContent.querySelector('img').style.borderRadius = '4px'; // Add rounded corners to the image

        // Styles for the description
        multipleRiskContent.querySelector('div').style.fontFamily = 'Arial, sans-serif'; // Change font family
        multipleRiskContent.querySelector('div').style.color = '#333'; // Set text color
        multipleRiskContent.querySelector('div').style.fontSize = '20px'; // Set font size
        multipleRiskContent.querySelector('div').style.marginLeft = '10px'; // Adjust left margin
    }

    

    // ... (Add similar logic for other visualizations)

    // Hide JSON content
    var scoreResult = document.getElementById('scoreResult');
    if (scoreResult) {
        scoreResult.style.display = 'none';
    }
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

function toggleCheckboxes(sectionId, sectionTag) {
    var checkboxContainer = document.getElementById(sectionId);
    var toggleButton = document.getElementById("toggleButton_" + sectionTag);

    // Check if the button exists, if not, create it
    if (!toggleButton) {
        toggleButton = document.createElement("button");
        toggleButton.id = "toggleButton_" + sectionTag;
        toggleButton.innerText = "+";
        toggleButton.style.cursor = "pointer";
        toggleButton.addEventListener("click", function() {
            toggleCheckboxContainer(checkboxContainer, toggleButton); // Pass toggleButton as an argument
        });
        // Append the button to the container
        checkboxContainer.parentNode.insertBefore(toggleButton, checkboxContainer);
    }

    toggleCheckboxContainer(checkboxContainer, toggleButton); // Pass toggleButton as an argument
}

function toggleCheckboxContainer(checkboxContainer, toggleButton) {
    var isExpanded = checkboxContainer.style.display === "block";

    if (isExpanded) {
        checkboxContainer.style.display = "none";
        toggleButton.innerText = "+";
        toggleButton.style.cursor = "pointer";
    } else {
        checkboxContainer.style.display = "block";
        toggleButton.innerText = "-";
        toggleButton.style.cursor = "pointer";
    }
}