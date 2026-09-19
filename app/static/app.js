let token = "";

const API_BASE = window.location.origin;


function $(id){
    return document.getElementById(id);
}


/**
 * API请求
 */
async function api(path, options={}){


    if(!token){

        token =
        localStorage.getItem("HL_TOKEN") || "";

    }


    const headers =
    options.headers || {};


    headers["Authorization"] =
    token;



    const res = await fetch(
        API_BASE + "/api" + path,
        {
            ...options,
            headers:headers
        }
    );


    if(!res.ok){

        throw new Error(
            "API请求失败: "+res.status
        );

    }


    return await res.json();

}



/**
 * 连接后台
 */
async function connectBackend(){


    token =
    $("token").value.trim();



    if(!token){

        alert(
        "请输入管理员令牌"
        );

        return;

    }



    localStorage.setItem(
        "HL_TOKEN",
        token
    );



    try{


        const data =
        await api("/status");



        msg(
        "✅ 后端连接成功"
        );


        console.log(data);


        await refresh();


    }


    catch(e){


        msg(
        "❌ "+e.message
        );


    }


}




function msg(text){

    const el =
    $("message");


    if(el){

        el.innerHTML=text;

    }

}



/**
 * 刷新数据
 */
async function refresh(){


    try{


        const data =
        await api("/status");


        const box =
        $("serverStatus");


        if(box){

            box.innerHTML =
            `
            服务:
            ${data.server || "online"}
            <br>
            数据库:
            ${data.database || "connected"}
            `;

        }


    }

    catch(e){

        console.log(e);

    }


}



/**
 * 上传视频
 */
async function uploadVideo(){


    const file =
    $("videoFile").files[0];


    if(!file){

        alert(
        "请选择视频"
        );

        return;

    }


    const form =
    new FormData();


    form.append(
        "file",
        file
    );



    try{


        await api(
            "/upload",
            {
                method:"POST",
                body:form,
                headers:{
                    "Authorization":token
                }
            }
        );


        alert(
        "上传成功"
        );


    }

    catch(e){


        alert(
        "上传失败："+e.message
        );


    }


}



window.onload=function(){


    const old =
    localStorage.getItem(
        "HL_TOKEN"
    );


    if(old && $("token")){

        $("token").value=old;

    }


};
