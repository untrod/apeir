#[cfg(target_os = "windows")]
use std::{ffi::c_void, ptr};

#[cfg(target_os = "windows")]
use windows_sys::Win32::Security::Credentials::{
    CredDeleteW, CredFree, CredReadW, CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE,
    CRED_TYPE_GENERIC,
};

const TARGET_PREFIX: &str = "Nous/provider-env/";

fn decode_credential_bytes(bytes: &[u8]) -> Result<String, String> {
    let decoded = if bytes.contains(&0) {
        if !bytes.len().is_multiple_of(2) {
            return Err("Stored provider credential has an invalid encoding.".to_string());
        }
        let (pairs, _) = bytes.as_chunks::<2>();
        let mut words = pairs
            .iter()
            .map(|pair| u16::from_le_bytes(*pair))
            .collect::<Vec<_>>();
        while words.last() == Some(&0) {
            words.pop();
        }
        let value = String::from_utf16(&words)
            .map_err(|_| "Stored provider credential is not valid UTF-16.".to_string())?;
        words.fill(0);
        value
    } else {
        String::from_utf8(bytes.to_vec())
            .map_err(|_| "Stored provider credential is not valid UTF-8.".to_string())?
    };
    if decoded.is_empty() || decoded.contains('\0') {
        return Err("Stored provider credential contains invalid data.".to_string());
    }
    Ok(decoded)
}

pub fn validate_environment_name(value: &str) -> Result<String, String> {
    let value = value.trim();
    let mut characters = value.chars();
    let first = characters
        .next()
        .ok_or_else(|| "Credential environment name is required.".to_string())?;
    if !(first == '_' || first.is_ascii_uppercase())
        || !characters.all(|character| {
            character == '_' || character.is_ascii_uppercase() || character.is_ascii_digit()
        })
        || value.len() > 128
    {
        return Err(
            "Credential environment name must use uppercase letters, digits, and underscores."
                .to_string(),
        );
    }
    Ok(value.to_string())
}

#[cfg(target_os = "windows")]
fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(target_os = "windows")]
pub fn store(environment_name: &str, secret: &str) -> Result<(), String> {
    let environment_name = validate_environment_name(environment_name)?;
    if secret.trim().is_empty() {
        return Err("Credential value is required.".to_string());
    }
    let mut target = wide(&format!("{TARGET_PREFIX}{environment_name}"));
    let mut username = wide(&environment_name);
    let mut blob = secret.as_bytes().to_vec();
    let credential = CREDENTIALW {
        Type: CRED_TYPE_GENERIC,
        TargetName: target.as_mut_ptr(),
        CredentialBlobSize: blob.len() as u32,
        CredentialBlob: blob.as_mut_ptr(),
        Persist: CRED_PERSIST_LOCAL_MACHINE,
        UserName: username.as_mut_ptr(),
        ..CREDENTIALW::default()
    };
    let written = unsafe { CredWriteW(&credential, 0) };
    blob.fill(0);
    if written == 0 {
        return Err(format!(
            "Windows Credential Manager could not store the credential: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(())
}

#[cfg(target_os = "windows")]
pub fn load(environment_name: &str) -> Result<Option<String>, String> {
    let environment_name = validate_environment_name(environment_name)?;
    let target = wide(&format!("{TARGET_PREFIX}{environment_name}"));
    let mut credential: *mut CREDENTIALW = ptr::null_mut();
    let read = unsafe { CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut credential) };
    if read == 0 {
        let error = std::io::Error::last_os_error();
        if error.raw_os_error() == Some(1168) {
            return Ok(None);
        }
        return Err(format!(
            "Windows Credential Manager could not read the credential: {error}"
        ));
    }
    if credential.is_null() {
        return Ok(None);
    }
    let mut bytes = unsafe {
        let value = &*credential;
        std::slice::from_raw_parts(
            value.CredentialBlob as *const u8,
            value.CredentialBlobSize as usize,
        )
        .to_vec()
    };
    unsafe {
        CredFree(credential as *const c_void);
    }
    let decoded = decode_credential_bytes(&bytes);
    bytes.fill(0);
    decoded.map(Some)
}

#[cfg(target_os = "windows")]
pub fn remove(environment_name: &str) -> Result<(), String> {
    let environment_name = validate_environment_name(environment_name)?;
    let target = wide(&format!("{TARGET_PREFIX}{environment_name}"));
    let removed = unsafe { CredDeleteW(target.as_ptr(), CRED_TYPE_GENERIC, 0) };
    if removed == 0 {
        let error = std::io::Error::last_os_error();
        if error.raw_os_error() != Some(1168) {
            return Err(format!(
                "Windows Credential Manager could not remove the credential: {error}"
            ));
        }
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
pub fn store(_environment_name: &str, _secret: &str) -> Result<(), String> {
    Err("System credential storage is not available on this platform.".to_string())
}

#[cfg(not(target_os = "windows"))]
pub fn load(_environment_name: &str) -> Result<Option<String>, String> {
    Ok(None)
}

#[cfg(not(target_os = "windows"))]
pub fn remove(_environment_name: &str) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{decode_credential_bytes, validate_environment_name};

    #[test]
    fn environment_names_are_strict_and_secret_safe() {
        assert_eq!(
            validate_environment_name("DEEPSEEK_API_KEY").expect("valid name"),
            "DEEPSEEK_API_KEY"
        );
        assert!(validate_environment_name("sk-secret-value").is_err());
        assert!(validate_environment_name("9INVALID").is_err());
    }

    #[test]
    fn credential_decoder_accepts_utf8_and_legacy_utf16le() {
        let sample_value = "temporary-secret";
        let legacy = sample_value
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect::<Vec<_>>();

        assert_eq!(
            decode_credential_bytes(sample_value.as_bytes()).unwrap(),
            sample_value
        );
        assert_eq!(decode_credential_bytes(&legacy).unwrap(), sample_value);
        assert!(decode_credential_bytes(b"bad\0x").is_err());
    }

    #[cfg(target_os = "windows")]
    #[test]
    fn windows_credential_round_trip_is_private_and_reversible() {
        let name = format!("NOUS_TEST_{}_KEY", std::process::id());
        let sample_value = "temporary-test-value";

        super::store(&name, sample_value).expect("store credential");
        assert_eq!(
            super::load(&name).expect("load credential").as_deref(),
            Some(sample_value)
        );
        super::remove(&name).expect("remove credential");
        assert_eq!(super::load(&name).expect("credential removed"), None);
    }
}
