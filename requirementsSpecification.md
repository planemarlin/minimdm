# Mini Master Data Managment (miniMDM) requirements specification

miniMDM is a minimal light-weight Master Data Management application featuring a web interface (client) with a database and API interface (server). The application should be open source and all software used/included should also be open source. The application could be deployed in a closed source environment but it shouldn't be a requirement to run the application.

## Technical specification

- Use open source database
- Python should be the main code base
- Use open source web server
- Security first approach
- Data sent over network should be kept to a minimal
- Web application should adapt to screen size, support for both desktop and mobile

## Non-technical specification

- The application should be open source and follow best practices for open source code base
- Documentation should follow best practice and include
    - README.md
    - Changelog.md
    - docs folder with
        - installation instruction
        - feature/reference documentation
        - list of software used in application
        - common errors and their solutions
        - tutorial and quick start guide
- API end point documentation should be generated and available in API
- Feature/function tests should be created and it should be possible to execute them easily
- Application language should be English but values entered should accept any language (Unicode)
- Error messages should be common and easy to understand

## Feature requirements

Implmentation should first focus on the core features and then additional features before moving on the non-prioritized features. Each feature should be implemented with knowledge of the other planned features.

### Core features

- Master Data Management web based application storing values in objects in a database through API end points
- Objects (tables) should be specified in a config file (Yaml/Json) and created/updated from a function
- Insert/updates/deletes of values in objects is done in the web interface
- Bulk import/export of csv/tsv/Json files should be possible
- Log frawework to monitor any changes of values including what, who, when, where and why the changes were made
- Historic values should be saved and versioned
- It should be possible to view historic values and revert to any previous version
- In the web application values should be searchable
- It should be possible to view multiple objects as they reference each other. But only one object at the time should be editable.

### Additional features

- Security - access should be controlled and only given by admins
    - Access by username and password (not recommended)
    - Access by token (to API)
    - Access by cloud logins, i.e. Azure Entra Id and similar in AWS and GCP
    - Access by on-prem network logins
- Save user preferences
- Use of schema in the database should be a way to group objects to set different access for different users/groups

### Non-prioritized features

- In-application help
- Function to alert when new version is available on Github
- Light mode and dark mode
- Colour variations in web interface
- Mobile app

## Other notes

Further features may be added in the future. The implementation should allow this.

## Example config file

### Yaml

```Yaml
minimdm
    - schemas
        - dev
            - objects
                - company
                    name: 'Company'
                    description: 'Legal Entity'
                    attributes:
                        - code
                            name: 'Code'
                            type: string
                            required: true
                        - name
                            name: 'Name'
                            type: string
                            required: false
                        - country
                            name: 'Country'
                            type: string
                - division
                    name: 'Division'
                    parent: company
                    description: 'Division is a grouping of Cost Centers'
                    attributes:
                        - code
                            name: 'Code'
                            type: string
                            required: true
                        - name
                            name: 'Division name'
                            type: string
                        - external_number
                            name: External division number'
                            type: numeric
                            required: false
                - cost_center
                    name: 'Cost Center'
                    parent: division
                    description: 'Cost Center is the lowest level'
                    attributes:
                        - code
                            name: 'Cost Center number'
                            type: string
                            required: true
                        - name
                            name: 'Cost Center name'
                            type: string
                        - manager
                            reference: manager
                            name: 'Cost Center manager'
                - manager:
                    name: 'Manager'
                    description: 'A manager responsible for one or more levels in the organization'
                    attributes:
                        - employee_number
                            name: 'Employee number'
                            type: string
                            required: true
                        - name
                            name: 'Manager name'
                            type: string
                        - title
                            name: 'Manager title'
                            type: string
                        - email
                            name: 'E-mail'
                            type: email
        - test
            - objects
                - test:
                    name: 'test'
                    description: 'test'
                    attributes:
                        - test
                            name: 'test'
                            type: string
                            required: true
                        - test2
                            name: 'test2'
                            type: string
                            required: false
```

### Json

```Json
````
